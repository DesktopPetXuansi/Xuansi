package api

import (
	"crypto/hmac"
	"errors"
	"net/http"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"xuansi/web/backend/internal/platform"
)

func validRegistrationCode(code string) bool {
	if len(code) != 6 {
		return false
	}
	for _, digit := range code {
		if digit < '0' || digit > '9' {
			return false
		}
	}
	return true
}

// 校验、一次性消费、新账号和会话同事务提交，成功后才写登录 Cookie。
func (s *Server) completeRegistration(w http.ResponseWriter, r *http.Request) {
	var input struct{ Email, ChallengeID, Code, Password string }
	if !decode(w, r, &input) {
		return
	}
	email, valid := normalizedEmail(input.Email)
	if !valid || uuid.Validate(input.ChallengeID) != nil || !validRegistrationCode(input.Code) {
		problem(w, r, 400, "REGISTRATION_CODE_INVALID", "验证码无效或已过期，请检查邮箱或重新获取")
		return
	}
	length := utf8.RuneCountInString(input.Password)
	if length < platform.PasswordMinLength || length > platform.PasswordMaxLength {
		invalid(w, r, "密码须为12至128个字符")
		return
	}
	var user platform.User
	var sessionToken string
	outcome := "REGISTRATION_CODE_INVALID"
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var challenge registrationChallenge
		err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=? AND email_hash=?", input.ChallengeID, s.registrationDigest("email", email)).First(&challenge).Error
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil
		}
		if err != nil {
			return err
		}
		now := time.Now().UTC()
		if challenge.ConsumedAt != nil || !challenge.ExpiresAt.After(now) || challenge.Attempts >= 5 {
			return nil
		}
		expected := s.registrationDigest("code", challenge.ID, email, input.Code)
		if !hmac.Equal([]byte(challenge.CodeHash), []byte(expected)) {
			// 业务拒绝在事务外返回，错码次数必须提交，不能随错误一起回滚。
			return tx.Model(&challenge).Update("attempts", challenge.Attempts+1).Error
		}
		if err := tx.Model(&challenge).Update("consumed_at", now).Error; err != nil {
			return err
		}
		var existing int64
		if err := tx.Model(&platform.User{}).Where("lower(email)=?", email).Count(&existing).Error; err != nil {
			return err
		}
		if existing > 0 {
			// 邮箱证明不能重置已有账号的密码、角色、禁用状态或登录身份。
			outcome = "EMAIL_ALREADY_REGISTERED"
			return nil
		}
		hash, err := platform.HashPassword(input.Password)
		if err != nil {
			return err
		}
		user = platform.User{ID: uuid.NewString(), Email: email, PasswordHash: hash, DisplayName: "新朋友", Role: "USER", Status: "ACTIVE", EmailVerified: true, QuotaBytes: s.Config.QuotaBytes, CreatedAt: now, UpdatedAt: now}
		if err := tx.Create(&user).Error; err != nil {
			return err
		}
		sessionToken = platform.RandomToken()
		session := platform.WebSession{ID: uuid.NewString(), UserID: user.ID, TokenHash: platform.Digest(sessionToken), CreatedAt: now, LastSeenAt: now, ExpiresAt: now.Add(platform.SessionLifetime)}
		if err := tx.Create(&session).Error; err != nil {
			return err
		}
		outcome = ""
		return nil
	})
	if errors.Is(err, gorm.ErrDuplicatedKey) {
		outcome, err = "EMAIL_ALREADY_REGISTERED", nil
	}
	if err != nil {
		s.registrationFailure(w, r, err)
		return
	}
	if outcome == "EMAIL_ALREADY_REGISTERED" {
		problem(w, r, 409, outcome, "该邮箱已有账号，请直接登录或找回密码")
		return
	}
	if outcome != "" {
		problem(w, r, 400, outcome, "验证码无效或已过期，请检查邮箱或重新获取")
		return
	}
	s.cookie(w, "xuansi_session", sessionToken, true, int(platform.SessionLifetime.Seconds()))
	s.Log.Info("邮箱验证码注册并登录成功", "userId", user.ID)
	reply(w, 201, user.View())
}
