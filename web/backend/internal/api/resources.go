package api

import (
	"encoding/base64"
	"encoding/json"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"strconv"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) resourceRoutes(r chi.Router) {
	r.Get("/resources", s.listResources(false))
	r.With(require).Get("/me/resources", s.listResources(true))
	r.Get("/resources/{id}", s.getResource)
	r.With(verified).Post("/resources", s.createResource)
	r.With(verified).Patch("/resources/{id}", s.patchResource)
	r.With(verified).Delete("/resources/{id}", s.deleteResource)
	r.Get("/resources/{id}/versions", s.listVersions)
	r.Get("/resources/{id}/versions/{versionId}", s.getVersion)
	r.Get("/resources/{id}/versions/{versionId}/manifest", s.manifest)
	r.Get("/resources/{id}/cover", s.cover)
	r.With(verified).Post("/resources/{id}/versions", s.createVersion)
	r.With(verified).Post("/uploads", s.createCover)
	r.With(verified).Put("/uploads/{id}/content", s.uploadContent)
	r.With(verified).Post("/uploads/{id}/completion", s.completeUpload)
	r.With(verified).Get("/uploads/{id}", s.getUpload)
	r.With(verified).Get("/me/uploads", s.listUploads)
	r.With(verified).Delete("/uploads/{id}", s.cancelUpload)
	r.Post("/resources/{id}/versions/{versionId}/download-authorizations", s.authorizeDownload)
	r.Get("/downloads/{ticket}", s.download)
	r.With(verified).Get("/me/library", s.library)
	r.With(verified).Put("/me/library/{id}", s.putLibrary)
	r.With(verified).Delete("/me/library/{id}", s.deleteLibrary)
}

// 单个资源与资源库批量查询共用读权限，后续购买权益在此接入。
func (s *Server) readableResources(r *http.Request) gorm.ChainInterface[platform.Resource] {
	q := gorm.G[platform.Resource](s.DB).Where("1=1")
	i := who(r)
	if i == nil {
		q = q.Where("visibility='PUBLIC' AND status='ACTIVE'")
	} else if i.User.Role != "ADMIN" || i.GrantID != "" {
		q = q.Where("owner_id = ? OR (visibility='PUBLIC' AND status='ACTIVE')", i.User.ID)
	}
	return q
}
func (s *Server) accessResource(r *http.Request, id string, ownerOnly bool) (platform.Resource, error) {
	q := s.readableResources(r).Where("id = ?", id)
	if ownerOnly {
		if who(r) == nil {
			return platform.Resource{}, gorm.ErrRecordNotFound
		}
		q = q.Where("owner_id = ?", who(r).User.ID)
	}
	res, e := q.First(r.Context())
	if e == nil && res.CoverKey != nil {
		url := "/api/v1/resources/" + res.ID + "/cover"
		res.CoverURL = &url
	}
	return res, e
}
func page(r *http.Request) (int, string) {
	n, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if n < 1 || n > 100 {
		n = 20
	}
	cursor := r.URL.Query().Get("cursor")
	b, e := base64.RawURLEncoding.DecodeString(cursor)
	if e != nil {
		return n, ""
	}
	if _, e = uuid.Parse(string(b)); e != nil {
		return n, ""
	}
	return n, string(b)
}
func listReply(w http.ResponseWriter, rows interface{}, cursor string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(map[string]interface{}{"data": rows, "meta": map[string]string{"nextCursor": cursor}})
}
func (s *Server) listResources(mine bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		limit, cursor := page(r)
		q := gorm.G[platform.Resource](s.DB).Where("1=1")
		if mine {
			q = q.Where("owner_id = ?", who(r).User.ID)
		} else {
			q = q.Where("visibility='PUBLIC' AND status='ACTIVE'")
		}
		// 官网挑选形象先按用途分组，再分页；旧客户端未传group时仍浏览全部资源。
		switch group := r.URL.Query().Get("group"); group {
		case "":
		case "APPEARANCE":
			q = q.Where("kind IN ?", []string{"MODEL", "IMAGE", "ANIMATION"})
		case "ADDON":
			q = q.Where("kind IN ?", []string{"MOTION", "EXPRESSION"})
		default:
			invalid(w, r, "资源分组无效")
			return
		}
		if cursor != "" {
			q = q.Where("id > ?", cursor)
		}
		if kind := r.URL.Query().Get("kind"); kind != "" {
			q = q.Where("kind = ?", kind)
		}
		if search := r.URL.Query().Get("search"); search != "" {
			q = q.Where("name ILIKE ?", "%"+search+"%")
		}
		if tag := r.URL.Query().Get("tag"); tag != "" {
			b, _ := json.Marshal([]string{tag})
			q = q.Where("tags @> ?::jsonb", string(b))
		}
		rows, e := q.Order("id ASC").Limit(limit + 1).Find(r.Context())
		if e != nil {
			s.fail(w, r, e)
			return
		}
		next := ""
		if len(rows) > limit {
			rows = rows[:limit]
			next = base64.RawURLEncoding.EncodeToString([]byte(rows[len(rows)-1].ID))
		}
		for i := range rows {
			if rows[i].CoverKey != nil {
				u := "/api/v1/resources/" + rows[i].ID + "/cover"
				rows[i].CoverURL = &u
			}
		}
		listReply(w, rows, next)
	}
}
func (s *Server) getResource(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, res)
}
func validKind(kind string) bool {
	switch kind {
	case "MODEL", "MOTION", "EXPRESSION", "IMAGE", "ANIMATION":
		return true
	}
	return false
}
func (s *Server) createResource(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Kind, Name, Description, Author, License, Source string
		Tags                                             []string
	}
	if !decode(w, r, &in) {
		return
	}
	if !validKind(in.Kind) || strings.TrimSpace(in.Name) == "" || len(in.Name) > 160 || len(in.Description) > 10000 || len(in.Tags) > 20 {
		invalid(w, r, "资源类型、名称或描述无效")
		return
	}
	tags, _ := json.Marshal(in.Tags)
	if in.Tags == nil {
		tags = []byte("[]")
	}
	res := platform.Resource{ID: uuid.NewString(), OwnerID: who(r).User.ID, Kind: in.Kind, Name: in.Name, Description: in.Description, Author: in.Author, License: in.License, Source: in.Source, Tags: tags, Visibility: "PRIVATE", Status: "ACTIVE", CreatedAt: time.Now(), UpdatedAt: time.Now()}
	if e := gorm.G[platform.Resource](s.DB).Create(r.Context(), &res); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 201, res)
}
func (s *Server) patchResource(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, true)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	var in struct {
		Name, Description, Author, License, Source, Status *string
		Tags                                               *[]string
		CurrentVersionID                                   *string
	}
	if who(r).GrantID != "" {
		// 检查原始字段，包括 null；写令牌只可选择已校验的当前版本。
		var fields map[string]json.RawMessage
		if !decode(w, r, &fields) {
			return
		}
		for field := range fields {
			if field != "currentVersionId" {
				problem(w, r, 403, "INSUFFICIENT_SCOPE", "客户端授权只允许设置当前版本")
				return
			}
		}
		if len(fields) != 1 || json.Unmarshal(fields["currentVersionId"], &in.CurrentVersionID) != nil || in.CurrentVersionID == nil {
			invalid(w, r, "请选择当前版本")
			return
		}
	} else if !decode(w, r, &in) {
		return
	}
	fields := map[string]interface{}{"updated_at": time.Now()}
	for key, value := range map[string]*string{"name": in.Name, "description": in.Description, "author": in.Author, "license": in.License, "source": in.Source} {
		if value != nil {
			if len(*value) > 10000 || key == "name" && (strings.TrimSpace(*value) == "" || len(*value) > 160) {
				invalid(w, r, "字段长度无效")
				return
			}
			fields[key] = *value
		}
	}
	if in.Status != nil {
		if *in.Status != "ACTIVE" && *in.Status != "HIDDEN" {
			invalid(w, r, "不允许的状态")
			return
		}
		fields["status"] = *in.Status
	}
	if in.Tags != nil {
		if len(*in.Tags) > 20 {
			invalid(w, r, "标签过多")
			return
		}
		b, _ := json.Marshal(*in.Tags)
		fields["tags"] = string(b)
	}
	if in.CurrentVersionID != nil {
		v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id = ? AND resource_id = ? AND validation_status='READY'", *in.CurrentVersionID, id).First(r.Context())
		if e != nil {
			invalid(w, r, "当前版本必须是本资源的已校验版本")
			return
		}
		fields["current_version_id"] = v.ID
	}
	e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		locked, e := gorm.G[platform.Resource](tx, clause.Locking{Strength: "UPDATE"}).Where("id=? AND owner_id=?", id, who(r).User.ID).First(r.Context())
		if e != nil {
			return e
		}
		if locked.Status == "DISABLED" && in.Status != nil {
			return ErrRule
		}
		return tx.Model(&platform.Resource{}).Where("id=?", id).Updates(fields).Error
	})
	if e == ErrRule {
		problem(w, r, 403, "RESOURCE_DISABLED", "停用资源只能由管理员恢复")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	res, e = s.accessResource(r, res.ID, true)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, res)
}
