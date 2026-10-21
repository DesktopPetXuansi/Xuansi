package api

import (
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"xuansi/web/backend/internal/resource"
)

var errFeedbackTransition = errors.New("当前反馈状态不允许此操作")

func (s *Server) moderateFeedback(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) {
		invalid(w, r, "反馈编号无效")
		return
	}
	var input struct {
		Decision string `json:"decision"`
	}
	if !decodeFeedback(w, r, &input) {
		return
	}
	if input.Decision != "APPROVE" && input.Decision != "SPAM" && input.Decision != "CONFIRM_WITHDRAWAL" {
		invalid(w, r, "审核操作无效")
		return
	}
	var row feedbackEntry
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&row).Error; err != nil {
			return err
		}
		switch input.Decision {
		case "APPROVE":
			if row.ModerationStatus == "APPROVED" && row.GitHubIssueNumber > 0 {
				return nil
			}
			if (row.ModerationStatus != "PENDING" && row.ModerationStatus != "APPROVED") || !row.PublicConsent || row.GitHubRepository == "" || row.GitHubRepository != s.Config.FeedbackGitHubRepository || row.GitHubPublic != s.Config.FeedbackGitHubPublic || s.Config.FeedbackGitHubToken == "" {
				return errFeedbackTransition
			}
			row.ModerationStatus = "APPROVED"
			// 审核与唯一投递责任同事务保存；恢复任务仍须原作者许可和原定渠道。
			if err := resource.QueueFeedback(r.Context(), tx, row.ID); err != nil {
				return err
			}
		case "SPAM":
			if row.ModerationStatus == "SPAM" {
				return nil
			}
			if (row.ModerationStatus != "PENDING" && row.ModerationStatus != "APPROVED") || row.PublicationStartedAt != nil || row.GitHubIssueNumber > 0 {
				return errFeedbackTransition
			}
			row.ModerationStatus = "SPAM"
		case "CONFIRM_WITHDRAWAL":
			if row.ModerationStatus == "WITHDRAWN" {
				return nil
			}
			if row.ModerationStatus != "WITHDRAWAL_REQUESTED" {
				return errFeedbackTransition
			}
			var running int64
			if err := tx.Table("jobs").Where("kind='FEEDBACK_GITHUB' AND status='RUNNING' AND payload->>'reviewedFeedbackId'=?", row.ID).Count(&running).Error; err != nil {
				return err
			}
			if running > 0 {
				return errFeedbackTransition
			}
			// 管理员须先在 GitHub 清理；不把关闭 Issue 当作删除公开内容。
			redactFeedback(&row)
			if err := saveFeedbackWithdrawal(tx, &row); err != nil {
				return err
			}
		}
		row.UpdatedAt = time.Now().UTC()
		if err := tx.Model(&row).Updates(map[string]interface{}{"moderation_status": row.ModerationStatus, "updated_at": row.UpdatedAt}).Error; err != nil {
			return err
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "feedback.moderation."+input.Decision, id)
	})
	switch {
	case errors.Is(err, gorm.ErrRecordNotFound):
		problem(w, r, 404, "NOT_FOUND", "反馈不存在")
	case errors.Is(err, errFeedbackTransition):
		problem(w, r, 409, "INVALID_FEEDBACK_TRANSITION", "当前状态、公开许可或投递渠道不允许此操作；正在投递时请稍后再处理")
	case err != nil:
		s.feedbackFailure(w, r)
	default:
		s.Log.Info("反馈审核已保存", "feedbackId", row.ID, "decision", input.Decision)
		reply(w, 200, row)
	}
}
