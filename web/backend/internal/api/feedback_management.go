package api

import (
	"crypto/subtle"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

type feedbackManagementInput struct {
	ManagementToken string `json:"managementToken"`
}

type feedbackManagement struct {
	ID               string    `json:"id"`
	CreatedAt        time.Time `json:"createdAt"`
	Status           string    `json:"status"`
	ModerationStatus string    `json:"moderationStatus"`
	GitHubIssueURL   string    `json:"githubIssueUrl"`
	CanWithdraw      bool      `json:"canWithdraw"`
}

var errFeedbackManagement = errors.New("反馈管理凭据无效")

func feedbackManagementView(row feedbackEntry) feedbackManagement {
	canWithdraw := row.ModerationStatus != "WITHDRAWN" && row.ModerationStatus != "WITHDRAWAL_REQUESTED" && row.PublicationStartedAt == nil && row.GitHubIssueNumber == 0
	return feedbackManagement{row.ID, row.CreatedAt, row.Status, row.ModerationStatus, row.GitHubIssueURL, canWithdraw}
}

// 凭据在请求正文中传输；不存在的编号与错误凭据使用相同错误，不泄露记录存在性。
func feedbackManagementAuthorized(row feedbackEntry, token string) bool {
	return validFeedbackToken(token) && row.ManagementTokenHash != "" && subtle.ConstantTimeCompare([]byte(row.ManagementTokenHash), []byte(feedbackDigest([]byte(token)))) == 1
}

func (s *Server) manageFeedback(w http.ResponseWriter, r *http.Request) {
	s.feedbackManagementRequest(w, r, false)
}

func (s *Server) withdrawFeedback(w http.ResponseWriter, r *http.Request) {
	s.feedbackManagementRequest(w, r, true)
}

func (s *Server) feedbackManagementRequest(w http.ResponseWriter, r *http.Request, withdraw bool) {
	var input feedbackManagementInput
	if !decodeFeedback(w, r, &input) {
		return
	}
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) || !validFeedbackToken(input.ManagementToken) {
		problem(w, r, 403, "INVALID_MANAGEMENT_TOKEN", "管理凭据无效，请使用保存的管理链接")
		return
	}
	var row feedbackEntry
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		query := tx.Where("id=?", id)
		if withdraw {
			// 与批准和 worker 的投递起始标记争用同一行锁，撤回结果才有明确顺序。
			query = query.Clauses(clause.Locking{Strength: "UPDATE"})
		}
		if err := query.First(&row).Error; err != nil {
			return err
		}
		if !feedbackManagementAuthorized(row, input.ManagementToken) {
			return errFeedbackManagement
		}
		if !withdraw || row.ModerationStatus == "WITHDRAWN" || row.ModerationStatus == "WITHDRAWAL_REQUESTED" {
			return nil
		}
		if row.PublicationStartedAt != nil || row.GitHubIssueNumber > 0 {
			row.ModerationStatus = "WITHDRAWAL_REQUESTED"
		} else {
			redactFeedback(&row)
		}
		return saveFeedbackWithdrawal(tx, &row)
	})
	switch {
	case errors.Is(err, gorm.ErrRecordNotFound), errors.Is(err, errFeedbackManagement):
		problem(w, r, 403, "INVALID_MANAGEMENT_TOKEN", "管理凭据无效，请使用保存的管理链接")
	case err != nil:
		s.feedbackFailure(w, r)
	default:
		if withdraw {
			s.Log.Info("反馈撤回状态已保存", "feedbackId", row.ID, "moderationStatus", row.ModerationStatus)
		}
		reply(w, 200, feedbackManagementView(row))
	}
}

func redactFeedback(row *feedbackEntry) {
	row.ModerationStatus = "WITHDRAWN"
	row.Title, row.Description, row.Contact = "", "", ""
	row.Diagnostics = nil
	row.GitHubIssueURL = ""
}

// 明确写入零值，保证撤回会真正清空正文、联系方式与诊断。
func saveFeedbackWithdrawal(tx *gorm.DB, row *feedbackEntry) error {
	row.UpdatedAt = time.Now().UTC()
	updates := map[string]interface{}{"moderation_status": row.ModerationStatus, "updated_at": row.UpdatedAt}
	if row.ModerationStatus == "WITHDRAWN" {
		updates["title"], updates["description"], updates["contact"] = "", "", ""
		updates["diagnostics"], updates["git_hub_issue_url"] = nil, ""
	}
	if err := tx.Model(row).Updates(updates).Error; err != nil {
		return err
	}
	// 发起外部清理时即删除私信正文，不等待最终公开内容撤回确认。
	return tx.Model(&feedbackMessage{}).Where("feedback_id=?", row.ID).Update("body", "").Error
}
