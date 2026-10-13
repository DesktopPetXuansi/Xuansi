package api

import (
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"time"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) library(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.UserLibrary](s.DB).Where("user_id=?", who(r).User.ID).Order("created_at DESC").Limit(1000).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	type item struct {
		Resource        platform.Resource `json:"resource"`
		PinnedVersionID *string           `json:"pinnedVersionId"`
	}
	out := []item{}
	if len(rows) == 0 {
		reply(w, 200, out)
		return
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.ResourceID)
	}
	resources, e := s.readableResources(r).Where("id IN ? AND status='ACTIVE'", ids).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	byID := make(map[string]platform.Resource, len(resources))
	for _, res := range resources {
		if res.CoverKey != nil {
			url := "/api/v1/resources/" + res.ID + "/cover"
			res.CoverURL = &url
		}
		byID[res.ID] = res
	}
	for _, row := range rows {
		if res, ok := byID[row.ResourceID]; ok {
			out = append(out, item{res, row.PinnedVersionID})
		}
	}
	reply(w, 200, out)
}
func (s *Server) putLibrary(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if res.Status != "ACTIVE" {
		invalid(w, r, "资源不可用")
		return
	}
	var in struct{ PinnedVersionID *string }
	if !decode(w, r, &in) {
		return
	}
	if in.PinnedVersionID != nil {
		if _, e = gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND resource_id=? AND validation_status='READY'", *in.PinnedVersionID, id).First(r.Context()); e != nil {
			invalid(w, r, "固定版本无效")
			return
		}
	}
	row := platform.UserLibrary{UserID: who(r).User.ID, ResourceID: id, PinnedVersionID: in.PinnedVersionID, CreatedAt: time.Now()}
	e = gorm.G[platform.UserLibrary](s.DB, clause.OnConflict{Columns: []clause.Column{{Name: "user_id"}, {Name: "resource_id"}}, DoUpdates: clause.AssignmentColumns([]string{"pinned_version_id"})}).Create(r.Context(), &row)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) deleteLibrary(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	if _, e := gorm.G[platform.UserLibrary](s.DB).Where("user_id=? AND resource_id=?", who(r).User.ID, id).Delete(r.Context()); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
