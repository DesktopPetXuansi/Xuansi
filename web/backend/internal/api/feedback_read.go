package api

import (
	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"time"
)

func (s *Server) accountReadFeedback(w http.ResponseWriter, r *http.Request) {
	s.markFeedbackRead(w, r, false)
}
func (s *Server) adminReadFeedback(w http.ResponseWriter, r *http.Request) {
	s.markFeedbackRead(w, r, true)
}

// 父锁串行读水位与新消息；旧页面迟到的确认只能前进，不能吞掉未来消息。
func (s *Server) markFeedbackRead(w http.ResponseWriter, r *http.Request, admin bool) {
	var in struct {
		MessageID string `json:"messageId"`
	}
	if !decodeFeedback(w, r, &in) {
		return
	}
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) || !canonicalFeedbackID(in.MessageID) {
		invalid(w, r, "消息编号无效")
		return
	}
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var row feedbackEntry
		if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&row).Error; e != nil {
			return e
		}
		if !admin && !accountOwns(row, r) {
			return gorm.ErrRecordNotFound
		}
		if feedbackHidden(row) {
			return nil
		}
		var at time.Time
		if in.MessageID == row.ID {
			at = row.CreatedAt
		} else {
			var msg feedbackMessage
			if e := tx.Where("id=? AND feedback_id=?", in.MessageID, id).First(&msg).Error; e != nil {
				return e
			}
			at = msg.CreatedAt
		}
		prefix := "owner"
		oldAt, oldID := row.OwnerReadAt, row.OwnerReadID
		if admin {
			prefix = "admin"
			oldAt, oldID = row.AdminReadAt, row.AdminReadID
		}
		if oldAt != nil && oldID != nil && (oldAt.After(at) || oldAt.Equal(at) && *oldID >= in.MessageID) {
			return nil
		}
		return tx.Model(&row).UpdateColumns(map[string]interface{}{prefix + "_read_at": at, prefix + "_read_id": in.MessageID}).Error
	})
	if err != nil {
		s.accountFeedbackError(w, r, err)
		return
	}
	reply(w, 204, nil)
}
