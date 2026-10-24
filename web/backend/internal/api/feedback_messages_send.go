package api

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
	"xuansi/web/backend/internal/platform"
)

type adminMessageInput struct {
	Body    string `json:"body"`
	Resolve bool   `json:"resolve,omitempty"`
}
type userMessageInput struct {
	ManagementToken string `json:"managementToken"`
	Body            string `json:"body"`
}
type messageReceipt struct {
	Message        feedbackMessage `json:"message"`
	FeedbackStatus string          `json:"feedbackStatus"`
}

func (s *Server) sendAdminFeedbackMessage(w http.ResponseWriter, r *http.Request) {
	s.sendFeedbackMessage(w, r, true)
}
func (s *Server) sendUserFeedbackMessage(w http.ResponseWriter, r *http.Request) {
	s.sendFeedbackMessage(w, r, false)
}

// 发送意图绑定真实管理员编号，仅摘要持久化；对用户视图永不返回身份。
func (s *Server) sendFeedbackMessage(w http.ResponseWriter, r *http.Request, admin bool) {
	account := strings.HasPrefix(r.URL.Path, "/api/v1/me/feedback/")
	id := chi.URLParam(r, "id")
	key := r.Header.Get("Idempotency-Key")
	var body, token, actor string
	resolve := false
	role := "USER"
	if admin {
		var in adminMessageInput
		if !decodeFeedback(w, r, &in) {
			return
		}
		body, resolve = in.Body, in.Resolve
		role, actor = "ADMIN", who(r).User.ID
	} else if account {
		var in struct {
			Body string `json:"body"`
		}
		if !decodeFeedback(w, r, &in) {
			return
		}
		body = in.Body
		actor = who(r).User.ID
	} else {
		var in userMessageInput
		if !decodeFeedback(w, r, &in) {
			return
		}
		body, token = in.Body, in.ManagementToken
	}

	if !canonicalFeedbackID(id) || (!admin && !account && !validFeedbackToken(token)) {
		if account {
			s.accountFeedbackError(w, r, gorm.ErrRecordNotFound)
		} else {
			s.messageReadError(w, r, admin, errFeedbackManagement)
		}
		return
	}
	body = strings.TrimSpace(body)
	if !canonicalFeedbackID(key) || utf8.RuneCountInString(body) < 1 || utf8.RuneCountInString(body) > 4000 {
		invalid(w, r, "请求编号或回复内容长度无效")
		return
	}
	intent, _ := json.Marshal(struct {
		Body    string
		Resolve bool
		Actor   string
	}{body, resolve, actor})
	hash := feedbackDigest(intent)
	now := time.Now().UTC().Truncate(time.Microsecond)
	message := feedbackMessage{ID: uuid.NewString(), FeedbackID: id, AuthorRole: role, Body: body, CreatedAt: now, IdempotencyKey: key, RequestHash: hash}
	if admin {
		message.AuthorName = "玄司开发者"
	} else if account {
		message.AuthorName = who(r).User.DisplayName
	}
	status := http.StatusCreated
	var feedbackStatus string
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var parent feedbackEntry
		// 与撤回、审核和每条回复串行，避免幂等重试恢复已删除内容。
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&parent).Error; e != nil {
			return e
		}
		if account && !accountOwns(parent, r) {
			return gorm.ErrRecordNotFound
		}
		if !admin && !account && !feedbackManagementAuthorized(parent, token) {
			return errFeedbackManagement
		}
		if !canReplyFeedback(parent) {
			return errFeedbackTransition
		}
		var existing feedbackMessage
		e := tx.Where("feedback_id=? AND author_role=? AND idempotency_key=?", id, role, key).First(&existing).Error
		if e == nil {
			if existing.RequestHash != hash {
				return errFeedbackConflict
			}
			existing.CreatedAt = existing.CreatedAt.UTC()
			message, status = existing, http.StatusOK
			// 重放保留原消息，但状态读取当前父行，避免覆盖对方后续处理。
			feedbackStatus = parent.Status
			return nil
		}
		if !errors.Is(e, gorm.ErrRecordNotFound) {
			return e
		}
		// 在父锁内确定消息时序，避免较早开始但较晚提交的消息落在已读水位之前。
		now = time.Now().UTC().Truncate(time.Microsecond)
		if !now.After(parent.UpdatedAt) {
			now = parent.UpdatedAt.Add(time.Microsecond)
		}
		message.CreatedAt = now
		// 独立带密钥来源摘要复用持久化额度，不占用初始反馈的额度。
		mac := hmac.New(sha256.New, []byte(s.Config.OAuthSecret))
		source := s.clientIP(r)
		if admin || account {
			source = actor
		}
		mac.Write([]byte("feedback-message:" + role + ":" + source))
		if e := reserveFeedbackQuota(tx, hex.EncodeToString(mac.Sum(nil)), now); e != nil {
			return e
		}
		next := parent.Status
		if !admin {
			next = "NEW"
		} else if resolve {
			next = "RESOLVED"
		} else if next == "NEW" {
			next = "IN_PROGRESS"
		}
		feedbackStatus = next
		if e := tx.Create(&message).Error; e != nil {
			return e
		}
		if e := tx.Model(&parent).Updates(map[string]interface{}{"status": next, "updated_at": now}).Error; e != nil {
			return e
		}
		// 匿名消息无可伪造的用户编号，审计允许 NULL actor；原文与凭据不进审计。
		if admin || account {
			return s.audit(r.Context(), tx, actor, "feedback.message."+role, message.ID)
		}
		return tx.Create(&platform.AuditLog{ID: uuid.NewString(), Action: "feedback.message.USER", TargetID: message.ID, Details: json.RawMessage(`{}`), CreatedAt: now}).Error
	})
	var limited *feedbackQuotaError
	switch {
	case errors.As(err, &limited):
		w.Header().Set("Retry-After", strconv.Itoa(limited.retryAfter))
		problem(w, r, 429, "RATE_LIMITED", "回复过于频繁，请稍后再试")
	case errors.Is(err, errFeedbackConflict):
		problem(w, r, 409, "CONFLICT", "此请求编号已经用于其他回复")
	case errors.Is(err, errFeedbackTransition):
		problem(w, r, 409, "INVALID_FEEDBACK_TRANSITION", "当前反馈已关闭对话，不能继续回复")
	case err != nil:
		if account {
			s.accountFeedbackError(w, r, err)
		} else {
			s.messageReadError(w, r, admin, err)
		}
	default:
		s.Log.Info("反馈私有消息已确认", "feedbackId", id, "messageId", message.ID, "role", role)
		reply(w, status, messageReceipt{message, feedbackStatus})
	}
}

func (s *Server) sendAccountFeedbackMessage(w http.ResponseWriter, r *http.Request) {
	s.sendFeedbackMessage(w, r, false)
}
