package api

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
	"xuansi/web/backend/internal/platform"
)

// 诊断只有主动授权的固定版本字段，不接收设备路径或自由日志。
type feedbackDiagnostics = platform.FeedbackDiagnostics
type feedbackInput struct {
	Category        string               `json:"category"`
	Title           string               `json:"title"`
	Description     string               `json:"description"`
	Contact         string               `json:"contact"`
	Diagnostics     *feedbackDiagnostics `json:"diagnostics"`
	PublicConsent   bool                 `json:"publicConsent,omitempty"`
	ManagementToken string               `json:"managementToken,omitempty"`
}
type feedbackEntry = platform.FeedbackEntry

type feedbackReceipt struct {
	ID        string    `json:"id"`
	CreatedAt time.Time `json:"createdAt"`
	Status    string    `json:"status"`
}

func feedbackStatus(v string) bool { return v == "NEW" || v == "IN_PROGRESS" || v == "RESOLVED" }
func canonicalFeedbackID(v string) bool {
	id, e := uuid.Parse(v)
	return e == nil && id != uuid.Nil && id.String() == v
}
func (in *feedbackInput) normalize() bool {
	in.Title = strings.TrimSpace(in.Title)
	in.Description = strings.TrimSpace(in.Description)
	in.Contact = strings.TrimSpace(in.Contact)
	if in.Category != "BUG" && in.Category != "SUGGESTION" && in.Category != "OTHER" {
		return false
	}
	if in.Title == "" || in.Description == "" || utf8.RuneCountInString(in.Title) > 80 || utf8.RuneCountInString(in.Description) > 4000 || utf8.RuneCountInString(in.Contact) > 160 {
		return false
	}
	if in.ManagementToken != "" && !validFeedbackToken(in.ManagementToken) {
		return false
	}
	if in.Diagnostics != nil {
		for _, v := range []*string{&in.Diagnostics.AppVersion, &in.Diagnostics.System, &in.Diagnostics.Architecture, &in.Diagnostics.PythonVersion, &in.Diagnostics.QtVersion} {
			*v = strings.TrimSpace(*v)
			if utf8.RuneCountInString(*v) > 80 {
				return false
			}
		}
	}
	return true
}

// 与现有解码器分离，反馈限制32KiB并拒绝尾随对象及未知嵌套字段。
func decodeFeedback(w http.ResponseWriter, r *http.Request, out interface{}) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 32<<10)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if e := d.Decode(out); e != nil {
		feedbackDecodeError(w, r, e)
		return false
	}
	var extra json.RawMessage
	if e := d.Decode(&extra); e != io.EOF {
		feedbackDecodeError(w, r, e)
		return false
	}
	return true
}
func feedbackDecodeError(w http.ResponseWriter, r *http.Request, e error) {
	var large *http.MaxBytesError
	if errors.As(e, &large) {
		problem(w, r, 413, "PAYLOAD_TOO_LARGE", "反馈内容超过请求大小限制")
		return
	}
	invalid(w, r, "反馈格式无效")
}
func (s *Server) feedbackRoutes(r chi.Router) {
	s.accountFeedbackRoutes(r)
	r.Post("/feedback", s.createFeedback)
	r.Post("/feedback/{id}/messages/query", s.queryFeedbackMessages)
	r.Post("/feedback/{id}/messages", s.sendUserFeedbackMessage)
	r.Post("/feedback/{id}/management", s.manageFeedback)
	r.Post("/feedback/{id}/withdrawal", s.withdrawFeedback)
}
func (s *Server) feedbackFailure(w http.ResponseWriter, r *http.Request) {
	// SQL错误可能含用户提供内容，只记固定事件及请求标识，由请求日志提供关联。
	s.Log.Error("反馈存储操作失败")
	problem(w, r, 500, "INTERNAL_ERROR", "服务暂时不可用")
}

type feedbackCursor struct {
	CreatedAt time.Time `json:"createdAt"`
	ID        string    `json:"id"`
	Status    string    `json:"status"`
}

func (s *Server) listFeedback(w http.ResponseWriter, r *http.Request) {
	status := r.URL.Query().Get("status")
	if status != "" && !feedbackStatus(status) {
		invalid(w, r, "反馈状态无效")
		return
	}
	limit := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		n, e := strconv.Atoi(raw)
		if e != nil || n < 1 || n > 100 {
			invalid(w, r, "分页大小无效")
			return
		}
		limit = n
	}
	q := gorm.G[feedbackEntry](s.DB)
	query := q.Where("1=1")
	if status != "" {
		query = query.Where("status=?", status)
	}
	if raw := r.URL.Query().Get("cursor"); raw != "" {
		b, e := base64.RawURLEncoding.DecodeString(raw)
		var c feedbackCursor
		if len(raw) > 1024 || e != nil || json.Unmarshal(b, &c) != nil || c.CreatedAt.IsZero() || !canonicalFeedbackID(c.ID) || c.Status != status {
			invalid(w, r, "游标无效")
			return
		}
		query = query.Where("(created_at,id)<(?,?)", c.CreatedAt, c.ID)
	}
	rows, e := query.Order("created_at DESC,id DESC").Limit(limit + 1).Find(r.Context())
	if e != nil {
		s.feedbackFailure(w, r)
		return
	}
	var next *string
	if len(rows) > limit {
		rows = rows[:limit]
		last := rows[len(rows)-1]
		b, _ := json.Marshal(feedbackCursor{last.CreatedAt, last.ID, status})
		v := base64.RawURLEncoding.EncodeToString(b)
		next = &v
	}
	if rows == nil {
		rows = []feedbackEntry{}
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(struct {
		Data []feedbackEntry `json:"data"`
		Meta struct {
			NextCursor *string `json:"nextCursor"`
		} `json:"meta"`
	}{Data: rows, Meta: struct {
		NextCursor *string `json:"nextCursor"`
	}{next}})
}
func (s *Server) patchFeedback(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	if !canonicalFeedbackID(id) {
		invalid(w, r, "反馈编号无效")
		return
	}
	var in struct {
		Status string `json:"status"`
	}
	if !decodeFeedback(w, r, &in) {
		return
	}
	if !feedbackStatus(in.Status) {
		invalid(w, r, "反馈状态无效")
		return
	}
	var row feedbackEntry
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		result := tx.Model(&feedbackEntry{}).Where("id=?", id).Updates(map[string]interface{}{"status": in.Status, "updated_at": time.Now().UTC()})
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return gorm.ErrRecordNotFound
		}
		if e := tx.Where("id=?", id).First(&row).Error; e != nil {
			return e
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "FEEDBACK_STATUS_"+in.Status, id)
	})
	if errors.Is(e, gorm.ErrRecordNotFound) {
		problem(w, r, 404, "NOT_FOUND", "反馈不存在")
		return
	}
	if e != nil {
		s.feedbackFailure(w, r)
		return
	}
	s.Log.Info("反馈状态已更新", "feedbackId", id, "status", in.Status)
	reply(w, 200, row)
}
