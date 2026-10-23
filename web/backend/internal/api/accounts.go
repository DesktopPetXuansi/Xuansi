package api

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"net/mail"
	"net/url"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) accountRoutes(r chi.Router) {
	r.Get("/auth/config", s.authConfig)
	r.Get("/auth/csrf", func(w http.ResponseWriter, r *http.Request) {
		token := platform.RandomToken()
		// 同一浏览器并行操作复用随机令牌，避免两次GET互相覆盖Cookie。
		if cookie, e := r.Cookie("xuansi_csrf"); e == nil {
			if raw, e := base64.RawURLEncoding.DecodeString(cookie.Value); e == nil && len(raw) == 32 {
				token = cookie.Value
			}
		}
		s.cookie(w, "xuansi_csrf", token, false, 3600)
		reply(w, 200, map[string]string{"token": token})
	})
	r.Post("/auth/register", s.register)
	r.Post("/auth/registration-codes", s.requestRegistrationCode)
	r.Post("/auth/registrations", s.completeRegistration)
	r.Post("/auth/login", s.login)
	r.Post("/auth/logout", s.logout)
	r.Post("/auth/email-verifications", s.requestToken("VERIFY"))
	r.Post("/auth/password-resets", s.requestToken("RESET"))
	r.Post("/auth/email-verifications/confirm", s.confirmToken("VERIFY"))
	r.Post("/auth/password-resets/confirm", s.confirmToken("RESET"))
	r.With(require).Get("/me", func(w http.ResponseWriter, r *http.Request) { reply(w, 200, who(r).User.View()) })
	r.With(require).Patch("/me", s.updateMe)
	r.With(require).Put("/me/password", s.changePassword)
	r.With(require).Get("/me/sessions", s.sessions)
	r.With(require).Delete("/me/sessions/{id}", s.deleteSession)
	r.With(require).Get("/me/client-grants", s.grants)
	r.With(require).Delete("/me/client-grants/{id}", s.deleteGrant)
}
func (s *Server) cookie(w http.ResponseWriter, name, value string, httpOnly bool, maxAge int) {
	http.SetCookie(w, &http.Cookie{Name: name, Value: value, Path: "/", HttpOnly: httpOnly, Secure: strings.HasPrefix(s.Config.AppURL, "https://"), SameSite: http.SameSiteLaxMode, MaxAge: maxAge})
}
func normalizedEmail(s string) (string, bool) {
	s = strings.ToLower(strings.TrimSpace(s))
	a, e := mail.ParseAddress(s)
	return s, e == nil && a.Address == s && len(s) <= 254
}
func (s *Server) register(w http.ResponseWriter, r *http.Request) {
	if s.mailDeliveryPaused(w, r) {
		return
	}
	var in struct{ Email, Password, DisplayName string }
	if !decode(w, r, &in) {
		return
	}
	email, ok := normalizedEmail(in.Email)
	if !ok || len(in.DisplayName) < 1 || len(in.DisplayName) > 80 {
		invalid(w, r, "邮箱或昵称无效")
		return
	}
	hash, e := platform.HashPassword(in.Password)
	if e != nil {
		invalid(w, r, e.Error())
		return
	}
	u := platform.User{ID: uuid.NewString(), Email: email, PasswordHash: hash, DisplayName: strings.TrimSpace(in.DisplayName), Role: "USER", Status: "ACTIVE", QuotaBytes: s.Config.QuotaBytes, CreatedAt: time.Now(), UpdatedAt: time.Now()}
	e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		// 旧缓存页面与同页验证码流程共享额度，不能成为额外发信通道。
		if err := s.registrationQuota(tx, r, email, time.Now().UTC()); err != nil {
			return err
		}
		if e := gorm.G[platform.User](tx).Create(r.Context(), &u); e != nil {
			return e
		}
		return s.issueAccountToken(r.Context(), tx, u, "VERIFY")
	})
	if e != nil {
		var limited *registrationRateError
		if errors.As(e, &limited) {
			registrationRateProblem(w, r, limited)
			return
		}
		s.fail(w, r, e)
		return
	}
	s.Log.Info("账号已注册", "userId", u.ID)
	reply(w, 201, u.View())
}
func (s *Server) login(w http.ResponseWriter, r *http.Request) {
	var in struct{ Email, Password string }
	if !decode(w, r, &in) {
		return
	}
	email, _ := normalizedEmail(in.Email)
	u, e := gorm.G[platform.User](s.DB).Where("email = ? AND status = 'ACTIVE'", email).First(r.Context())
	if e != nil || !platform.CheckPassword(u.PasswordHash, in.Password) {
		problem(w, r, 401, "INVALID_CREDENTIALS", "邮箱或密码不正确")
		return
	}
	token := platform.RandomToken()
	session := platform.WebSession{ID: uuid.NewString(), UserID: u.ID, TokenHash: platform.Digest(token), CreatedAt: time.Now(), LastSeenAt: time.Now(), ExpiresAt: time.Now().Add(platform.SessionLifetime)}
	if e = gorm.G[platform.WebSession](s.DB).Create(r.Context(), &session); e != nil {
		s.fail(w, r, e)
		return
	}
	s.cookie(w, "xuansi_session", token, true, int(platform.SessionLifetime.Seconds()))
	s.Log.Info("账号已登录", "userId", u.ID)
	reply(w, 200, u.View())
}
func (s *Server) logout(w http.ResponseWriter, r *http.Request) {
	if i := who(r); i != nil && i.SessionID != "" {
		if _, e := gorm.G[platform.WebSession](s.DB).Where("id = ?", i.SessionID).Delete(r.Context()); e != nil {
			s.fail(w, r, e)
			return
		}
	}
	s.cookie(w, "xuansi_session", "", true, -1)
	reply(w, 204, nil)
}

// 邮件和一次性令牌在同一事务创建，SMTP 故障由持久化 worker 重试。
func (s *Server) issueAccountToken(ctx context.Context, tx *gorm.DB, u platform.User, purpose string) error {
	raw := platform.RandomToken()
	token := platform.AccountToken{ID: uuid.NewString(), UserID: u.ID, Purpose: purpose, TokenHash: platform.Digest(raw), ExpiresAt: time.Now().Add(time.Hour)}
	if e := gorm.G[platform.AccountToken](tx).Create(ctx, &token); e != nil {
		return e
	}
	page, subject := "verify-email", "验证玄司账号邮箱"
	if purpose == "RESET" {
		page = "reset-password"
		subject = "重置玄司账号密码"
	}
	payload, _ := json.Marshal(map[string]string{"to": u.Email, "subject": subject, "body": "请在1小时内打开链接：\r\n" + s.Config.AppURL + "/" + page + "?token=" + url.QueryEscape(raw)})
	return gorm.G[platform.Job](tx).Create(ctx, &platform.Job{ID: uuid.NewString(), Kind: "MAIL", Payload: payload, Status: "QUEUED", RunAt: time.Now(), CreatedAt: time.Now()})
}
func (s *Server) requestToken(purpose string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.mailDeliveryPaused(w, r) {
			return
		}
		var in struct{ Email string }
		if !decode(w, r, &in) {
			return
		}
		email, valid := normalizedEmail(in.Email)
		if !valid {
			invalid(w, r, "请输入有效的邮箱地址")
			return
		}
		e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
			// 所有有效邮箱先走相同额度，不能通过冷却状态探测账号是否存在。
			if purpose == "VERIFY" {
				if err := s.registrationQuota(tx, r, email, time.Now().UTC()); err != nil {
					return err
				}
			}
			u, err := gorm.G[platform.User](tx).Where("email=? AND status='ACTIVE'", email).First(r.Context())
			if errors.Is(err, gorm.ErrRecordNotFound) {
				return nil
			}
			if err != nil {
				return err
			}
			return s.issueAccountToken(r.Context(), tx, u, purpose)
		})
		if e != nil {
			var limited *registrationRateError
			if errors.As(e, &limited) {
				registrationRateProblem(w, r, limited)
				return
			}
			s.fail(w, r, e)
			return
		}
		reply(w, 202, map[string]string{"message": "若邮箱符合条件，邮件将发送至该地址"})
	}
}
func (s *Server) confirmToken(purpose string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var in struct{ Token, Password string }
		if !decode(w, r, &in) {
			return
		}
		var hash string
		var e error
		if purpose == "RESET" {
			hash, e = platform.HashPassword(in.Password)
			if e != nil {
				invalid(w, r, e.Error())
				return
			}
		}
		e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
			token, e := gorm.G[platform.AccountToken](tx, clause.Locking{Strength: "UPDATE"}).Where("token_hash = ? AND purpose = ? AND consumed_at IS NULL AND expires_at > ?", platform.Digest(in.Token), purpose, time.Now()).First(r.Context())
			if e != nil {
				return e
			}
			u, e := gorm.G[platform.User](tx, clause.Locking{Strength: "UPDATE"}).Where("id = ? AND status = 'ACTIVE'", token.UserID).First(r.Context())
			if e != nil {
				return e
			}
			if _, e = gorm.G[platform.AccountToken](tx).Where("id = ?", token.ID).Update(r.Context(), "consumed_at", time.Now()); e != nil {
				return e
			}
			if purpose == "VERIFY" {
				_, e = gorm.G[platform.User](tx).Where("id = ?", u.ID).Update(r.Context(), "email_verified", true)
				return e
			}
			if _, e = gorm.G[platform.User](tx).Where("id = ?", u.ID).Update(r.Context(), "password_hash", hash); e != nil {
				return e
			}
			return revokeUser(r.Context(), tx, u.ID)
		})
		if e != nil {
			if errors.Is(e, gorm.ErrRecordNotFound) {
				problem(w, r, 400, "TOKEN_INVALID", "链接无效或已过期")
				return
			}
			s.fail(w, r, e)
			return
		}
		reply(w, 204, nil)
	}
}
func revokeUser(ctx context.Context, tx *gorm.DB, id string) error {
	if _, e := gorm.G[platform.WebSession](tx).Where("user_id = ?", id).Delete(ctx); e != nil {
		return e
	}
	if _, e := gorm.G[platform.OAuthGrant](tx).Where("user_id = ?", id).Update(ctx, "revoked_at", time.Now()); e != nil {
		return e
	}
	return tx.WithContext(ctx).Exec("UPDATE oauth_records SET active=false WHERE grant_id IN (SELECT id FROM oauth_grants WHERE user_id=?)", id).Error
}
func (s *Server) updateMe(w http.ResponseWriter, r *http.Request) {
	var in struct{ DisplayName string }
	if !decode(w, r, &in) {
		return
	}
	if len(strings.TrimSpace(in.DisplayName)) == 0 || len(in.DisplayName) > 80 {
		invalid(w, r, "昵称长度应为1至80字节")
		return
	}
	u := who(r).User
	u.DisplayName = strings.TrimSpace(in.DisplayName)
	if _, e := gorm.G[platform.User](s.DB).Where("id = ?", u.ID).Update(r.Context(), "display_name", u.DisplayName); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, u.View())
}
func (s *Server) changePassword(w http.ResponseWriter, r *http.Request) {
	var in struct{ CurrentPassword, Password string }
	if !decode(w, r, &in) {
		return
	}
	u := who(r).User
	if !platform.CheckPassword(u.PasswordHash, in.CurrentPassword) {
		problem(w, r, 401, "INVALID_CREDENTIALS", "当前密码不正确")
		return
	}
	hash, e := platform.HashPassword(in.Password)
	if e != nil {
		invalid(w, r, e.Error())
		return
	}
	e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if _, e := gorm.G[platform.User](tx).Where("id = ?", u.ID).Update(r.Context(), "password_hash", hash); e != nil {
			return e
		}
		return revokeUser(r.Context(), tx, u.ID)
	})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	s.cookie(w, "xuansi_session", "", true, -1)
	reply(w, 204, nil)
}
func (s *Server) sessions(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.WebSession](s.DB).Where("user_id = ? AND expires_at > ?", who(r).User.ID, time.Now()).Order("created_at DESC").Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	for i := range rows {
		rows[i].IsCurrent = rows[i].ID == who(r).SessionID
	}
	reply(w, 200, rows)
}
func (s *Server) deleteSession(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	n, e := gorm.G[platform.WebSession](s.DB).Where("id = ? AND user_id = ?", id, who(r).User.ID).Delete(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if n == 0 {
		s.fail(w, r, gorm.ErrRecordNotFound)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) grants(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.OAuthGrant](s.DB).Where("user_id = ? AND revoked_at IS NULL", who(r).User.ID).Order("created_at DESC").Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}
func (s *Server) deleteGrant(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	n, e := gorm.G[platform.OAuthGrant](s.DB).Where("id = ? AND user_id = ?", id, who(r).User.ID).Update(r.Context(), "revoked_at", time.Now())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if n == 0 {
		s.fail(w, r, gorm.ErrRecordNotFound)
		return
	}
	reply(w, 204, nil)
}
