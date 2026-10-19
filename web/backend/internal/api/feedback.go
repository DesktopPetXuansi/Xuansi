package api

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// 诊断只有主动授权的固定版本字段，不接收设备路径或自由日志。
type feedbackDiagnostics struct {
	AppVersion    string `json:"appVersion,omitempty"`
	System        string `json:"system,omitempty"`
	Architecture  string `json:"architecture,omitempty"`
	PythonVersion string `json:"pythonVersion,omitempty"`
	QtVersion     string `json:"qtVersion,omitempty"`
}
type feedbackInput struct {
	Category    string               `json:"category"`
	Title       string               `json:"title"`
	Description string               `json:"description"`
	Contact     string               `json:"contact"`
	Diagnostics *feedbackDiagnostics `json:"diagnostics"`
}
type feedbackEntry struct {
	ID             string               `json:"id"`
	IdempotencyKey string               `json:"-"`
	RequestHash    string               `json:"-"`
	Category       string               `json:"category"`
	Title          string               `json:"title"`
	Description    string               `json:"description"`
	Contact        string               `json:"contact"`
	Diagnostics    *feedbackDiagnostics `json:"diagnostics" gorm:"serializer:json"`
	Status         string               `json:"status"`
	CreatedAt      time.Time            `json:"createdAt"`
	UpdatedAt      time.Time            `json:"updatedAt"`
}

func (feedbackEntry) TableName() string { return "feedback" }

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
func (s *Server) feedbackRoutes(r chi.Router) { r.Post("/feedback", s.createFeedback) }
func (s *Server) feedbackFailure(w http.ResponseWriter, r *http.Request) {
	// SQL错误可能含用户提供内容，只记固定事件及请求标识，由请求日志提供关联。
	s.Log.Error("反馈存储操作失败")
	problem(w, r, 500, "INTERNAL_ERROR", "服务暂时不可用")
}
func (s *Server) createFeedback(w http.ResponseWriter, r *http.Request) {
	key := r.Header.Get("Idempotency-Key")
	if !canonicalFeedbackID(key) {
		invalid(w, r, "请求编号必须为标准UUID")
		return
	}
	var in feedbackInput
	if !decodeFeedback(w, r, &in) {
		return
	}
	if !in.normalize() {
		invalid(w, r, "请检查反馈类型及内容长度")
		return
	}
	body, _ := json.Marshal(in)
	sum := sha256.Sum256(body)
	now := time.Now().UTC().Truncate(time.Microsecond)
	row := feedbackEntry{ID: key, IdempotencyKey: key, RequestHash: hex.EncodeToString(sum[:]), Category: in.Category, Title: in.Title, Description: in.Description, Contact: in.Contact, Diagnostics: in.Diagnostics, Status: "NEW", CreatedAt: now, UpdatedAt: now}
	result := gorm.WithResult()
	e := gorm.G[feedbackEntry](s.DB, result, clause.OnConflict{Columns: []clause.Column{{Name: "idempotency_key"}}, DoNothing: true}).Create(r.Context(), &row)
	if e != nil {
		s.feedbackFailure(w, r)
		return
	}
	status := 201
	if result.RowsAffected == 0 {
		old, e := gorm.G[feedbackEntry](s.DB).Where("idempotency_key=?", key).First(r.Context())
		if e != nil {
			s.feedbackFailure(w, r)
			return
		}
		if old.RequestHash != row.RequestHash {
			problem(w, r, 409, "CONFLICT", "此请求编号已经用于其他反馈")
			return
		}
		row = old
		status = 200
	}
	s.Log.Info("反馈提交已确认", "feedbackId", row.ID)
	// 状态更新不改变最初收据，提交重试始终得到相同的NEW收据。
	reply(w, status, feedbackReceipt{row.ID, row.CreatedAt.UTC(), "NEW"})
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
