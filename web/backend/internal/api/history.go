package api

import (
	"encoding/json"
	"errors"
	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"io"
	"net/http"
	"strconv"
	"time"
	"xuansi/web/backend/internal/history"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) historyRoutes(r chi.Router) {
	r.With(require).Get("/me/history", s.listHistory)
	r.With(require).Put("/me/history/{id}", s.putHistory)
	r.With(require).Delete("/me/history/{id}", s.deleteHistory)
	r.With(require).Delete("/me/history", s.clearHistory)
}
func historyKind(w http.ResponseWriter, r *http.Request) (string, bool) {
	kind := r.URL.Query().Get("kind")
	if kind != "" && kind != "APPEARANCE" && kind != "DOWNLOAD" {
		invalid(w, r, "历史类别无效")
		return "", false
	}
	return kind, true
}
func (s *Server) listHistory(w http.ResponseWriter, r *http.Request) {
	kind, ok := historyKind(w, r)
	if !ok {
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
	q := gorm.G[history.Entry](s.DB).Where("user_id=?", who(r).User.ID)
	if kind != "" {
		q = q.Where("kind=?", kind)
	}
	if raw := r.URL.Query().Get("cursor"); raw != "" {
		c, e := history.DecodeCursor(raw, kind)
		if e != nil {
			invalid(w, r, "游标无效")
			return
		}
		q = q.Where("(occurred_at,id)<(?,?)", c.Time, c.ID)
	}
	rows, e := q.Order("occurred_at DESC,id DESC").Limit(limit + 1).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	var next *string
	if len(rows) > limit {
		rows = rows[:limit]
		v := history.EncodeCursor(rows[len(rows)-1], kind)
		next = &v
	}
	if rows == nil {
		rows = []history.Entry{}
	}
	// 单次批量查询可读资源，避免历史列表逐行查询和暴露已变私有的元数据。
	ids := []string{}
	for _, row := range rows {
		if row.ResourceID != nil {
			ids = append(ids, *row.ResourceID)
		}
	}
	readable := map[string]bool{}
	if len(ids) > 0 {
		type readyVersion struct{ ID string }
		versions := []readyVersion{}
		e = s.DB.WithContext(r.Context()).Table("resource_versions v").Select("v.id").Joins("JOIN resources r ON r.id=v.resource_id").Where("r.id IN ? AND r.status='ACTIVE' AND v.validation_status='READY' AND (r.owner_id=? OR r.visibility='PUBLIC')", ids, who(r).User.ID).Scan(&versions).Error
		if e != nil {
			s.fail(w, r, e)
			return
		}
		for _, v := range versions {
			readable[v.ID] = true
		}
	}
	for i := range rows {
		row := &rows[i]
		row.Available = row.ResourceID == nil
		if row.ResourceVersionID != nil {
			row.Available = readable[*row.ResourceVersionID]
		}
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(struct {
		Data []history.Entry `json:"data"`
		Meta struct {
			NextCursor *string `json:"nextCursor"`
		} `json:"meta"`
	}{Data: rows, Meta: struct {
		NextCursor *string `json:"nextCursor"`
	}{next}})
}
func (s *Server) putHistory(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	var in history.Input
	// 独立的小请求上限与 EOF 检查，避免尾随对象夹带秘密字段。
	r.Body = http.MaxBytesReader(w, r.Body, 8<<10)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if e := decoder.Decode(&in); e != nil {
		invalid(w, r, "历史格式无效")
		return
	}
	var trailing json.RawMessage
	if e := decoder.Decode(&trailing); e != io.EOF || !in.Validate(time.Now()) {
		invalid(w, r, "历史内容无效")
		return
	}
	row := in.Entry(who(r).User.ID, id)
	// 已成功写入的同内容重试不依赖资源当前状态，资源失效不会破坏幂等。
	old, e := gorm.G[history.Entry](s.DB).Where("user_id=? AND id=?", row.UserID, id).First(r.Context())
	if e == nil {
		if old.RequestHash != row.RequestHash {
			problem(w, r, 409, "CONFLICT", "历史记录内容冲突")
			return
		}
		reply(w, 204, nil)
		return
	}
	if !errors.Is(e, gorm.ErrRecordNotFound) {
		s.fail(w, r, e)
		return
	}
	if row.ResourceID != nil {
		res, e := s.accessResource(r, *row.ResourceID, false)
		if e != nil {
			s.fail(w, r, e)
			return
		}
		if res.Status != "ACTIVE" || res.Kind != in.AppearanceKind {
			invalid(w, r, "形象资源不可用或类型不匹配")
			return
		}
		v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND resource_id=? AND validation_status='READY'", *row.ResourceVersionID, res.ID).First(r.Context())
		if e != nil {
			s.fail(w, r, e)
			return
		}
		row.Name = res.Name
		row.Version = &v.Version
	}
	if e = history.Put(r.Context(), s.DB, row); errors.Is(e, history.ErrConflict) {
		problem(w, r, 409, "CONFLICT", "历史记录内容冲突")
		return
	} else if e != nil {
		s.fail(w, r, e)
		return
	}
	s.Log.Info("形象历史已保存", "historyId", id)
	reply(w, 204, nil)
}
func (s *Server) deleteHistory(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	if _, e := gorm.G[history.Entry](s.DB).Where("user_id=? AND id=?", who(r).User.ID, id).Delete(r.Context()); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) clearHistory(w http.ResponseWriter, r *http.Request) {
	kind, ok := historyKind(w, r)
	if !ok {
		return
	}
	q := gorm.G[history.Entry](s.DB).Where("user_id=?", who(r).User.ID)
	if kind != "" {
		q = q.Where("kind=?", kind)
	}
	if _, e := q.Delete(r.Context()); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
