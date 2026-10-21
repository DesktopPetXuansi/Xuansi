package api

import (
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"xuansi/web/backend/internal/platform"
)

type registrationChallenge struct {
	EmailHash  string `gorm:"primaryKey"`
	ID         string
	CodeHash   string
	Attempts   int
	ExpiresAt  time.Time
	ResendAt   time.Time
	ConsumedAt *time.Time
	UpdatedAt  time.Time
}

func (registrationChallenge) TableName() string { return "registration_challenges" }

type registrationCodeReceipt struct {
	ChallengeID string    `json:"challengeId"`
	ExpiresAt   time.Time `json:"expiresAt"`
	ResendAt    time.Time `json:"resendAt"`
}

// 取码只创建短期挑战和邮件任务，不预建用户，也不返回验证码。
func (s *Server) requestRegistrationCode(w http.ResponseWriter, r *http.Request) {
	var input struct{ Email string }
	if !decode(w, r, &input) {
		return
	}
	email, valid := normalizedEmail(input.Email)
	if !valid {
		invalid(w, r, "请输入有效的邮箱地址")
		return
	}
	number, err := rand.Int(rand.Reader, big.NewInt(1000000))
	if err != nil {
		s.registrationFailure(w, r, err)
		return
	}
	code := fmt.Sprintf("%06d", number.Int64())
	now := time.Now().UTC()
	challenge := registrationChallenge{
		ID: uuid.NewString(), EmailHash: s.registrationDigest("email", email),
		ExpiresAt: now.Add(10 * time.Minute), ResendAt: now.Add(time.Minute), UpdatedAt: now,
	}
	challenge.CodeHash = s.registrationDigest("code", challenge.ID, email, code)
	err = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if err := s.registrationQuota(tx, r, email, now); err != nil {
			return err
		}
		// 邮箱唯一约束协调并发重发；新编号/摘要生效后旧验证码立即失效。
		if err := tx.Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "email_hash"}},
			DoUpdates: clause.AssignmentColumns([]string{"id", "code_hash", "attempts", "expires_at", "resend_at", "consumed_at", "updated_at"}),
		}).Create(&challenge).Error; err != nil {
			return err
		}
		payload, err := json.Marshal(struct {
			To, Subject, Body string
			RegistrationID    string `json:"registrationId"`
		}{email, "玄司注册验证码", "你的注册验证码是：" + code + "\r\n10 分钟内有效，请回到注册页面输入。请勿向任何人透露验证码。如非本人操作，请忽略。", challenge.ID})
		if err != nil {
			return err
		}
		return tx.Create(&platform.Job{ID: uuid.NewString(), Kind: "MAIL", Payload: payload, Status: "QUEUED", RunAt: now, CreatedAt: now}).Error
	})
	if err != nil {
		s.registrationFailure(w, r, err)
		return
	}
	s.Log.Info("注册验证码已入邮件队列", "challengeId", challenge.ID)
	reply(w, 202, registrationCodeReceipt{challenge.ID, challenge.ExpiresAt, challenge.ResendAt})
}

func (s *Server) registrationFailure(w http.ResponseWriter, r *http.Request, err error) {
	var limited *registrationRateError
	if errors.As(err, &limited) {
		registrationRateProblem(w, r, limited)
		return
	}
	// 数据库或 SMTP 的原始错误可能包含输入；这里只记录固定事件和请求编号。
	s.Log.Error("注册操作暂时失败")
	problem(w, r, 500, "REGISTRATION_UNAVAILABLE", "暂时无法完成注册操作，请稍后重试")
}
