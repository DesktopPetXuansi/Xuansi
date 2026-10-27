package api

import (
	"net/http"

	"gorm.io/gorm"
)

// 一次清空全部分页的垃圾反馈；保留原投稿与消息的幂等凭据，重试不能复活正文。
func (s *Server) clearFeedbackSpam(w http.ResponseWriter, r *http.Request) {
	var result struct {
		ClearedCount int64 `json:"clearedCount"`
	}
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		// 父行先加锁，再批量擦除正文和私信；与审核、撤回及消息写入共享同一锁边界。
		// 仅处理未开始公开投递的垃圾，已公开内容仍走原人工清理流程。
		if err := tx.Raw(`WITH targets AS (
		 SELECT id FROM feedback WHERE moderation_status='SPAM' AND cleared_at IS NULL
		 AND publication_started_at IS NULL AND git_hub_issue_number=0 ORDER BY id FOR UPDATE
		), cleared AS (
		 UPDATE feedback AS f SET title='',description='',contact='',diagnostics=NULL,submitter_name='',
		 git_hub_issue_url='',admin_read_at=NULL,admin_read_id=NULL,owner_read_at=NULL,owner_read_id=NULL,
		 cleared_at=now(),updated_at=now() FROM targets AS t WHERE f.id=t.id RETURNING f.id
		), cleared_messages AS (
		 UPDATE feedback_messages SET body='',author_name='' WHERE feedback_id IN (SELECT id FROM cleared)
		) SELECT count(*) AS cleared_count FROM cleared`).Scan(&result).Error; err != nil {
			return err
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "feedback.spam.clear", "spam")
	})
	if err != nil {
		s.feedbackFailure(w, r)
		return
	}
	s.Log.Info("垃圾反馈已清空", "clearedCount", result.ClearedCount)
	reply(w, http.StatusOK, result)
}
