package api

import (
	"errors"
	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"time"
)

// 网站账号反馈不继承桌面 OAuth 权限。
func feedbackWebSession(next http.Handler) http.Handler {
	return require(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if who(r).SessionID == "" || who(r).GrantID != "" {
			problem(w, r, 403, "FORBIDDEN", "请使用网站账号会话")
			return
		}
		if expected := r.Header.Get("X-Feedback-Account"); expected != "" && expected != who(r).User.ID {
			problem(w, r, 409, "ACCOUNT_CHANGED", "账号已切换，请刷新后重试")
			return
		}
		next.ServeHTTP(w, r)
	}))
}
func (s *Server) accountFeedbackRoutes(r chi.Router) {
	r.Route("/me/feedback", func(r chi.Router) {
		r.Use(feedbackWebSession)
		r.Get("/", s.accountFeedbackThreads)
		r.Post("/", s.createAccountFeedback)
		r.Get("/{id}/messages", s.accountFeedbackMessages)
		r.Post("/{id}/messages", s.sendAccountFeedbackMessage)
		r.Post("/{id}/read", s.accountReadFeedback)
		r.Post("/{id}/withdrawal", s.withdrawAccountFeedback)
		r.Post("/{id}/claim", s.claimAccountFeedback)
	})
}
func accountOwns(row feedbackEntry, r *http.Request) bool {
	return row.OwnerUserID != nil && *row.OwnerUserID == who(r).User.ID
}
func feedbackHidden(row feedbackEntry) bool {
	return row.ModerationStatus == "WITHDRAWN" || row.ModerationStatus == "WITHDRAWAL_REQUESTED"
}
func (s *Server) accountFeedbackError(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, gorm.ErrRecordNotFound) || errors.Is(err, errFeedbackManagement) {
		problem(w, r, 404, "NOT_FOUND", "反馈不存在")
		return
	}
	if errors.Is(err, errFeedbackTransition) {
		problem(w, r, 409, "INVALID_FEEDBACK_TRANSITION", "当前反馈已关闭")
		return
	}
	s.feedbackFailure(w, r)
}
func (s *Server) claimAccountFeedback(w http.ResponseWriter, r *http.Request) {
	var in feedbackManagementInput
	if !decodeFeedback(w, r, &in) {
		return
	}
	var row feedbackEntry
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) || !validFeedbackToken(in.ManagementToken) {
		s.accountFeedbackError(w, r, gorm.ErrRecordNotFound)
		return
	}
	var thread feedbackThread
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&row).Error; e != nil {
			return e
		}
		if row.OwnerUserID != nil && !accountOwns(row, r) {
			return gorm.ErrRecordNotFound
		}
		// 未绑定记录先验证原权限，关闭状态不能泄漏给错误凭据持有者。
		if row.OwnerUserID == nil && !feedbackManagementAuthorized(row, in.ManagementToken) {
			return gorm.ErrRecordNotFound
		}
		if feedbackHidden(row) || row.ModerationStatus == "SPAM" {
			return errFeedbackTransition
		}
		if row.OwnerUserID == nil {
			uid := who(r).User.ID
			row.OwnerUserID = &uid
			row.ManagementTokenHash = ""
			row.UpdatedAt = time.Now().UTC()
			// 不回填匿名初始问题或历史消息的昵称。
			if e := tx.Model(&row).Updates(map[string]interface{}{"owner_user_id": uid, "management_token_hash": "", "updated_at": row.UpdatedAt}).Error; e != nil {
				return e
			}
			if e := s.audit(r.Context(), tx, uid, "feedback.claim", row.ID); e != nil {
				return e
			}
		}
		var e error
		thread, e = s.feedbackThreadView(tx, row, false)
		return e
	})
	if err != nil {
		s.accountFeedbackError(w, r, err)
		return
	}
	s.Log.Info("反馈已关联账号", "feedbackId", id)
	reply(w, 200, thread)
}
func (s *Server) withdrawAccountFeedback(w http.ResponseWriter, r *http.Request) {
	var input struct{}
	if !decodeFeedback(w, r, &input) {
		return
	}
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) {
		s.accountFeedbackError(w, r, gorm.ErrRecordNotFound)
		return
	}
	var row feedbackEntry
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&row).Error; e != nil {
			return e
		}
		if !accountOwns(row, r) {
			return gorm.ErrRecordNotFound
		}
		if feedbackHidden(row) {
			return nil
		}
		if row.PublicationStartedAt != nil || row.GitHubIssueNumber > 0 {
			row.ModerationStatus = "WITHDRAWAL_REQUESTED"
		} else {
			redactFeedback(&row)
		}
		return saveFeedbackWithdrawal(tx, &row)
	})
	if err != nil {
		s.accountFeedbackError(w, r, err)
		return
	}
	s.Log.Info("账号反馈撤回已保存", "feedbackId", id)
	reply(w, 200, feedbackManagementView(row))
}
