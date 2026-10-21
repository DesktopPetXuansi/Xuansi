package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"log/slog"
	"net/http"
	"slices"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
)

type Server struct {
	DB      *gorm.DB
	Config  platform.Config
	Storage platform.ObjectStorage
	Log     *slog.Logger
	OAuth   OAuthService
}
type OAuthService interface {
	Authorize(http.ResponseWriter, *http.Request)
	Token(http.ResponseWriter, *http.Request)
	Revoke(http.ResponseWriter, *http.Request)
	Authenticate(context.Context, string) (string, string, []string, error)
}
type identityKey struct{}
type Identity struct {
	User               platform.User
	SessionID, GrantID string
	Scopes             []string
}

// CurrentUser 为OAuth协议层提供已由中间件验证的身份。
func CurrentUser(r *http.Request) *platform.User {
	if i := who(r); i != nil {
		return &i.User
	}
	return nil
}

func who(r *http.Request) *Identity { i, _ := r.Context().Value(identityKey{}).(*Identity); return i }
func (s *Server) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, middleware.Recoverer, s.headers, s.rateLimit, s.authentication, s.requestLog)
	r.Get("/healthz", func(w http.ResponseWriter, r *http.Request) {
		reply(w, 200, map[string]string{"status": "ok"})
	})
	// 就绪探针检查数据库；存活探针不因数据库暂时不可达而重启进程。
	r.Get("/readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		sql, e := s.DB.DB()
		if e == nil {
			e = sql.PingContext(ctx)
		}
		if e != nil {
			s.fail(w, r, e)
			return
		}
		reply(w, 200, map[string]string{"status": "ok"})
	})
	r.Route("/api/v1", func(r chi.Router) {
		r.Use(s.csrf)
		s.accountRoutes(r)
		s.resourceRoutes(r)
		s.historyRoutes(r)
		s.feedbackRoutes(r)
		s.releaseRoutes(r)
		s.adminRoutes(r)
	})
	if s.OAuth != nil {
		r.Get("/oauth/authorize", s.OAuth.Authorize)
		r.With(s.csrf).Post("/oauth/authorize", s.OAuth.Authorize)
		r.Post("/oauth/token", s.OAuth.Token)
		r.Post("/oauth/revoke", s.OAuth.Revoke)
	}
	return r
}
func (s *Server) headers(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		next.ServeHTTP(w, r)
	})
}
func (s *Server) requestLog(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		s.Log.Info("HTTP请求完成", "method", r.Method, "route", chi.RouteContext(r.Context()).RoutePattern(), "durationMs", time.Since(start).Milliseconds(), "requestId", middleware.GetReqID(r.Context()))
	})
}
func (s *Server) authentication(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var uid, sid, gid string
		var scopes []string
		if auth := r.Header.Get("Authorization"); strings.HasPrefix(auth, "Bearer ") && s.OAuth != nil {
			var e error
			uid, gid, scopes, e = s.OAuth.Authenticate(r.Context(), strings.TrimPrefix(auth, "Bearer "))
			if e != nil {
				problem(w, r, 401, "UNAUTHORIZED", "客户端授权已失效")
				return
			}
		} else if cookie, e := r.Cookie("xuansi_session"); e == nil {
			session, e := gorm.G[platform.WebSession](s.DB).Where("token_hash = ? AND expires_at > ?", platform.Digest(cookie.Value), time.Now()).First(r.Context())
			if e == nil {
				uid = session.UserID
				sid = session.ID
			}
		}
		if uid != "" {
			u, e := gorm.G[platform.User](s.DB).Where("id = ? AND status = 'ACTIVE'", uid).First(r.Context())
			if e == nil {
				r = r.WithContext(context.WithValue(r.Context(), identityKey{}, &Identity{User: u, SessionID: sid, GrantID: gid, Scopes: scopes}))
				if sid != "" {
					_ = s.DB.WithContext(r.Context()).Exec("UPDATE web_sessions SET last_seen_at=now() WHERE id=? AND last_seen_at<now()-interval '5 minutes'", sid).Error
				}
				if gid != "" {
					_ = s.DB.WithContext(r.Context()).Exec("UPDATE oauth_grants SET last_seen_at=now() WHERE id=? AND last_seen_at<now()-interval '5 minutes'", gid).Error
				}
			}
		}
		if gid != "" && !bearerAllowed(r.Method, r.URL.Path, scopes) {
			problem(w, r, 403, "INSUFFICIENT_SCOPE", "客户端授权不允许此操作")
			return
		}
		next.ServeHTTP(w, r)
	})
}

// 精确匹配方法和路由段，新增网站接口不会隐式继承桌面客户端权限。
func bearerAllowed(method, path string, scopes []string) bool {
	if !slices.Contains(scopes, "resources:read") || !strings.HasPrefix(path, "/api/v1/") {
		return false
	}
	p := strings.Split(strings.TrimPrefix(path, "/api/v1/"), "/")
	id := func(value string) bool { _, e := uuid.Parse(value); return e == nil }
	// 历史是独立授权，已有资源读取/上传令牌不能隐式读取或同步个人行为。
	if path == "/api/v1/me/history" || len(p) == 3 && p[0] == "me" && p[1] == "history" && id(p[2]) {
		read := slices.Contains(scopes, "history:read")
		write := slices.Contains(scopes, "history:write")
		return read && (method == "GET" && len(p) == 2 || write && (method == "DELETE" || method == "PUT" && len(p) == 3))
	}
	if method == "GET" {
		if path == "/api/v1/me" || path == "/api/v1/me/library" || path == "/api/v1/me/resources" || path == "/api/v1/resources" || path == "/api/v1/client/releases" {
			return true
		}
		if len(p) == 3 && p[0] == "client" && p[1] == "releases" && (p[2] == "latest" || id(p[2])) {
			return true
		}
		if len(p) >= 2 && p[0] == "resources" && id(p[1]) {
			if len(p) == 2 || len(p) == 3 && (p[2] == "versions" || p[2] == "cover") {
				return true
			}
			if len(p) == 4 && p[2] == "versions" && id(p[3]) || len(p) == 5 && p[2] == "versions" && id(p[3]) && p[4] == "manifest" {
				return true
			}
		}
	}
	if method == "POST" && len(p) == 5 && p[0] == "resources" && id(p[1]) && p[2] == "versions" && id(p[3]) && p[4] == "download-authorizations" {
		return true
	}
	if !slices.Contains(scopes, "resources:write") {
		return false
	}
	if method == "POST" && path == "/api/v1/resources" {
		return true
	}
	if len(p) == 2 && p[0] == "resources" && id(p[1]) {
		return method == "PATCH"
	}
	if len(p) == 3 && p[0] == "resources" && id(p[1]) && p[2] == "versions" {
		return method == "POST"
	}
	if len(p) == 2 && p[0] == "uploads" && id(p[1]) {
		return method == "GET" || method == "DELETE"
	}
	if len(p) == 3 && p[0] == "uploads" && id(p[1]) {
		return p[2] == "content" && method == "PUT" || p[2] == "completion" && method == "POST"
	}
	return len(p) == 3 && p[0] == "me" && p[1] == "library" && id(p[2]) && method == "PUT"
}

// 双提交 Cookie 配合精确 Origin；Bearer 请求具有独立的客户端授权边界。
func (s *Server) csrf(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == "GET" || r.Method == "HEAD" || r.Method == "OPTIONS" {
			next.ServeHTTP(w, r)
			return
		}
		if strings.HasPrefix(r.Header.Get("Authorization"), "Bearer ") {
			if who(r) == nil {
				problem(w, r, 401, "UNAUTHORIZED", "请登录")
				return
			}
			next.ServeHTTP(w, r)
			return
		}
		cookie, e := r.Cookie("xuansi_csrf")
		origin := r.Header.Get("Origin")
		if e != nil || cookie.Value == "" || cookie.Value != r.Header.Get("X-CSRF-Token") || origin != s.Config.AppURL {
			problem(w, r, 403, "CSRF_FAILED", "请求校验失败，请刷新后重试")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func require(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if who(r) == nil {
			problem(w, r, 401, "UNAUTHORIZED", "请登录")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func verified(next http.Handler) http.Handler {
	return require(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !who(r).User.EmailVerified {
			problem(w, r, 403, "EMAIL_UNVERIFIED", "请先验证邮箱")
			return
		}
		if who(r).GrantID != "" && !bearerAllowed(r.Method, r.URL.Path, who(r).Scopes) {
			problem(w, r, 403, "INSUFFICIENT_SCOPE", "客户端授权不允许此操作")
			return
		}
		next.ServeHTTP(w, r)
	}))
}
func admin(next http.Handler) http.Handler {
	return require(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if who(r).User.Role != "ADMIN" || who(r).GrantID != "" {
			problem(w, r, 403, "FORBIDDEN", "管理员权限不足")
			return
		}
		next.ServeHTTP(w, r)
	}))
}
func reply(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if status != 204 {
		_ = json.NewEncoder(w).Encode(struct {
			Data interface{} `json:"data"`
		}{data})
	}
}
func problem(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]interface{}{"error": map[string]string{"code": code, "message": message}, "requestId": middleware.GetReqID(r.Context())})
}
func (s *Server) fail(w http.ResponseWriter, r *http.Request, e error) {
	if errors.Is(e, gorm.ErrRecordNotFound) {
		problem(w, r, 404, "NOT_FOUND", "内容不存在或不可访问")
		return
	}
	if errors.Is(e, gorm.ErrDuplicatedKey) || errors.Is(e, gorm.ErrForeignKeyViolated) {
		problem(w, r, 409, "CONFLICT", "数据冲突或仍被引用")
		return
	}
	s.Log.Error("业务请求失败", "requestId", middleware.GetReqID(r.Context()), "error", e)
	problem(w, r, 500, "INTERNAL_ERROR", "服务暂时不可用")
}
func decode(w http.ResponseWriter, r *http.Request, v interface{}) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		problem(w, r, 400, "INVALID_INPUT", "请求格式无效")
		return false
	}
	return true
}
func validID(w http.ResponseWriter, r *http.Request, key string) (string, bool) {
	s := chi.URLParam(r, key)
	if _, e := uuid.Parse(s); e != nil {
		problem(w, r, 400, "INVALID_ID", "ID格式无效")
		return "", false
	}
	return s, true
}
func (s *Server) audit(ctx context.Context, tx *gorm.DB, actor, action, target string) error {
	return gorm.G[platform.AuditLog](tx).Create(ctx, &platform.AuditLog{ID: uuid.NewString(), ActorID: &actor, Action: action, TargetID: target, Details: json.RawMessage(`{}`), CreatedAt: time.Now()})
}
func invalid(w http.ResponseWriter, r *http.Request, message string) {
	problem(w, r, 400, "INVALID_INPUT", message)
}

var ErrRule = fmt.Errorf("业务规则冲突")
