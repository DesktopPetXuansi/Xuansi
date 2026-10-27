package api

import (
	"encoding/base64"
	"encoding/json"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"strconv"
	"time"
)

type feedbackParticipant struct {
	Kind        string `json:"kind"`
	DisplayName string `json:"displayName"`
}
type feedbackThread struct {
	ID               string              `json:"id"`
	Title            string              `json:"title"`
	Preview          string              `json:"preview"`
	Status           string              `json:"status"`
	ModerationStatus string              `json:"moderationStatus"`
	Participant      feedbackParticipant `json:"participant"`
	CreatedAt        time.Time           `json:"createdAt"`
	UpdatedAt        time.Time           `json:"updatedAt"`
	UnreadCount      int64               `json:"unreadCount"`
	CanReply         bool                `json:"canReply"`
	LastMessage      *feedbackMessage    `json:"lastMessage"`
}

func feedbackParticipantView(tx *gorm.DB, row feedbackEntry) (feedbackParticipant, error) {
	out := feedbackParticipant{"GUEST", "访客"}
	if row.OwnerUserID != nil && !feedbackHidden(row) {
		var name string
		if e := tx.Table("users").Select("display_name").Where("id=?", *row.OwnerUserID).Scan(&name).Error; e != nil {
			return out, e
		}
		out = feedbackParticipant{"ACCOUNT", name}
	}
	return out, nil
}

// 已读边界以真实消息位置比较；管理员包含初始问题，所有者仅统计开发者回复。
func feedbackUnread(tx *gorm.DB, row feedbackEntry, admin bool) (int64, error) {
	if feedbackHidden(row) {
		return 0, nil
	}
	at, id, role := row.OwnerReadAt, row.OwnerReadID, "ADMIN"
	if admin {
		at, id, role = row.AdminReadAt, row.AdminReadID, "USER"
	}
	q := tx.Model(&feedbackMessage{}).Where("feedback_id=? AND author_role=?", row.ID, role)
	if at != nil && id != nil {
		q = q.Where("(created_at,id)>(?,?)", *at, *id)
	}
	var count int64
	if e := q.Count(&count).Error; e != nil {
		return 0, e
	}
	if admin && (at == nil || id == nil || row.CreatedAt.After(*at) || row.CreatedAt.Equal(*at) && row.ID > *id) {
		count++
	}
	return count, nil
}
func (s *Server) feedbackThreadView(tx *gorm.DB, row feedbackEntry, admin bool) (feedbackThread, error) {
	out := feedbackThread{ID: row.ID, Title: row.Title, Status: row.Status, ModerationStatus: row.ModerationStatus, CreatedAt: row.CreatedAt, UpdatedAt: row.UpdatedAt, CanReply: canReplyFeedback(row)}
	if feedbackHidden(row) {
		out.Title = ""
		out.Participant = feedbackParticipant{"GUEST", "访客"}
		return out, nil
	}
	runes := []rune(row.Description)
	if len(runes) > 160 {
		runes = runes[:160]
	}
	out.Preview = string(runes)
	var e error
	out.Participant, e = feedbackParticipantView(tx, row)
	if e != nil {
		return out, e
	}
	out.UnreadCount, e = feedbackUnread(tx, row, admin)
	if e != nil {
		return out, e
	}
	var msgs []feedbackMessage
	if e = tx.Where("feedback_id=?", row.ID).Order("created_at DESC,id DESC").Limit(1).Find(&msgs).Error; e != nil {
		return out, e
	}
	if len(msgs) > 0 {
		out.LastMessage = &msgs[0]
	}
	return out, nil
}
func (s *Server) accountFeedbackThreads(w http.ResponseWriter, r *http.Request) {
	s.feedbackThreads(w, r, false)
}
func (s *Server) adminFeedbackThreads(w http.ResponseWriter, r *http.Request) {
	s.feedbackThreads(w, r, true)
}
func (s *Server) feedbackThreads(w http.ResponseWriter, r *http.Request, admin bool) {
	status := r.URL.Query().Get("status")
	if status != "" && !feedbackStatus(status) {
		invalid(w, r, "反馈状态无效")
		return
	}
	limit := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		n, e := strconv.Atoi(raw)
		if e != nil || n < 1 || n > 50 {
			invalid(w, r, "分页大小无效")
			return
		}
		limit = n
	}
	raw := r.URL.Query().Get("cursor")
	var cursor feedbackCursor
	if raw != "" {
		b, e := base64.RawURLEncoding.DecodeString(raw)
		if len(raw) > 1024 || e != nil || json.Unmarshal(b, &cursor) != nil || cursor.CreatedAt.IsZero() || !canonicalFeedbackID(cursor.ID) || cursor.Status != status || cursor.Folder != "" {
			invalid(w, r, "游标无效")
			return
		}
	}
	out := []feedbackThread{}
	var next *string
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		q := tx.Clauses(clause.Locking{Strength: "SHARE"}).Where("cleared_at IS NULL")
		if admin {
			// 对话待处理列表和收件箱遵循相同的垃圾隔离规则。
			q = q.Where("moderation_status<>'SPAM'")
		} else {
			q = q.Where("owner_user_id=?", who(r).User.ID)
		}
		if status != "" {
			q = q.Where("status=?", status)
		}
		if raw != "" {
			q = q.Where("(updated_at,id)<(?,?)", cursor.CreatedAt, cursor.ID)
		}
		var rows []feedbackEntry
		if e := q.Order("updated_at DESC,id DESC").Limit(limit + 1).Find(&rows).Error; e != nil {
			return e
		}
		if len(rows) > limit {
			rows = rows[:limit]
			last := rows[len(rows)-1]
			b, _ := json.Marshal(feedbackCursor{CreatedAt: last.UpdatedAt, ID: last.ID, Status: status})
			v := base64.RawURLEncoding.EncodeToString(b)
			next = &v
		}
		var err error
		out, err = feedbackThreadBatch(tx, rows, admin)
		return err
	})
	if err != nil {
		s.feedbackFailure(w, r)
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(struct {
		Data []feedbackThread `json:"data"`
		Meta struct {
			NextCursor *string `json:"nextCursor"`
		} `json:"meta"`
	}{out, struct {
		NextCursor *string `json:"nextCursor"`
	}{next}})
}
