package api

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"strconv"
	"time"
	"xuansi/web/backend/internal/platform"
)

type feedbackMessage = platform.FeedbackMessage

// 游标绑定反馈编号，倒序选择最新一页后反转为自然对话顺序。
type messageCursor struct {
	FeedbackID string    `json:"feedbackId"`
	CreatedAt  time.Time `json:"createdAt"`
	ID         string    `json:"id"`
}
type messageQuery struct {
	ManagementToken string `json:"managementToken"`
	Cursor          string `json:"cursor,omitempty"`
	Limit           *int   `json:"limit,omitempty"`
}
type feedbackConversation struct {
	ID               string               `json:"id"`
	Title            string               `json:"title"`
	Description      string               `json:"description"`
	Status           string               `json:"status"`
	ModerationStatus string               `json:"moderationStatus"`
	CanReply         bool                 `json:"canReply"`
	Participant      *feedbackParticipant `json:"participant,omitempty"`
	SubmitterName    string               `json:"submitterName,omitempty"`
	CreatedAt        time.Time            `json:"createdAt"`
	UnreadCount      int64                `json:"unreadCount"`
	Contact          *string              `json:"contact,omitempty"`
	Messages         []feedbackMessage    `json:"messages"`
}

func canReplyFeedback(row feedbackEntry) bool {
	return (row.ManagementTokenHash != "" || row.OwnerUserID != nil) && (row.ModerationStatus == "PENDING" || row.ModerationStatus == "APPROVED")
}
func (s *Server) queryFeedbackMessages(w http.ResponseWriter, r *http.Request) {
	s.readFeedbackMessages(w, r, false)
}
func (s *Server) adminFeedbackMessages(w http.ResponseWriter, r *http.Request) {
	s.readFeedbackMessages(w, r, true)
}
func (s *Server) readFeedbackMessages(w http.ResponseWriter, r *http.Request, admin bool) {
	account := r.Method == http.MethodGet && !admin
	var in messageQuery
	if admin || account {
		in.Cursor = r.URL.Query().Get("cursor")
		if raw, ok := r.URL.Query()["limit"]; ok {
			n, e := strconv.Atoi(raw[0])
			if e != nil {
				invalid(w, r, "分页大小无效")
				return
			}
			in.Limit = &n
		}
	} else if !decodeFeedback(w, r, &in) {
		return
	}
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) || (!admin && !account && !validFeedbackToken(in.ManagementToken)) {
		if account {
			s.accountFeedbackError(w, r, gorm.ErrRecordNotFound)
		} else {
			s.messageReadError(w, r, admin, errFeedbackManagement)
		}
		return
	}
	limit := 20
	if in.Limit != nil {
		limit = *in.Limit
	}
	if limit < 1 || limit > 50 {
		invalid(w, r, "分页大小无效")
		return
	}
	var cursor messageCursor
	if in.Cursor != "" {
		b, e := base64.RawURLEncoding.DecodeString(in.Cursor)
		if len(in.Cursor) > 1024 || e != nil || json.Unmarshal(b, &cursor) != nil || cursor.FeedbackID != id || !canonicalFeedbackID(cursor.ID) || cursor.CreatedAt.IsZero() {
			invalid(w, r, "游标无效")
			return
		}
	}
	var row feedbackEntry
	rows := []feedbackMessage{}
	var next *string
	var participant feedbackParticipant
	var unread int64
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		// 鉴权、读取正文与撤回共享同一父行锁，避免凭据校验后读到已撤回正文。
		if e := tx.Clauses(clause.Locking{Strength: "SHARE"}).Where("id=?", id).First(&row).Error; e != nil {
			return e
		}
		if account && !accountOwns(row, r) {
			return gorm.ErrRecordNotFound
		}
		if !admin && !account && !feedbackManagementAuthorized(row, in.ManagementToken) {
			return errFeedbackManagement
		}
		if feedbackHidden(row) {
			row.Title, row.Description, row.Contact, row.SubmitterName = "", "", "", ""
			participant = feedbackParticipant{"GUEST", "访客"}
			return nil
		}
		var e error
		participant, e = feedbackParticipantView(tx, row)
		if e != nil {
			return e
		}
		unread, e = feedbackUnread(tx, row, admin)
		if e != nil {
			return e
		}
		q := tx.Where("feedback_id=?", id)
		if in.Cursor != "" {
			q = q.Where("(created_at,id)<(?,?)", cursor.CreatedAt, cursor.ID)
		}
		if e := q.Order("created_at DESC,id DESC").Limit(limit + 1).Find(&rows).Error; e != nil {
			return e
		}
		if len(rows) > limit {
			rows = rows[:limit]
			last := rows[len(rows)-1]
			b, _ := json.Marshal(messageCursor{id, last.CreatedAt, last.ID})
			v := base64.RawURLEncoding.EncodeToString(b)
			next = &v
		}
		for left, right := 0, len(rows)-1; left < right; left, right = left+1, right-1 {
			rows[left], rows[right] = rows[right], rows[left]
		}
		return nil
	})
	if err != nil {
		if account {
			s.accountFeedbackError(w, r, err)
		} else {
			s.messageReadError(w, r, admin, err)
		}
		return
	}
	view := feedbackConversation{ID: row.ID, Title: row.Title, Description: row.Description, Status: row.Status, ModerationStatus: row.ModerationStatus, CanReply: canReplyFeedback(row), Messages: rows, Participant: &participant, SubmitterName: row.SubmitterName, CreatedAt: row.CreatedAt, UnreadCount: unread}
	if admin {
		view.Contact = &row.Contact
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(struct {
		Data feedbackConversation `json:"data"`
		Meta struct {
			NextCursor *string `json:"nextCursor"`
		} `json:"meta"`
	}{Data: view, Meta: struct {
		NextCursor *string `json:"nextCursor"`
	}{next}})
}
func (s *Server) messageReadError(w http.ResponseWriter, r *http.Request, admin bool, err error) {
	switch {
	case errors.Is(err, gorm.ErrRecordNotFound) || errors.Is(err, errFeedbackManagement):
		if admin {
			problem(w, r, 404, "NOT_FOUND", "反馈不存在")
		} else {
			problem(w, r, 403, "INVALID_MANAGEMENT_TOKEN", "管理凭据无效，请使用保存的管理链接")
		}
	default:
		s.feedbackFailure(w, r)
	}
}

func (s *Server) accountFeedbackMessages(w http.ResponseWriter, r *http.Request) {
	s.readFeedbackMessages(w, r, false)
}
