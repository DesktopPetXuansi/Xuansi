package api

import (
	"github.com/go-chi/chi/v5"
	"gorm.io/gorm"
	"net/http"
	"strconv"
	"xuansi/web/backend/internal/platform"
)

func formatBytes(n int64) string { return strconv.FormatInt(n, 10) }
func (s *Server) releaseRoutes(r chi.Router) {
	r.Get("/client/releases", s.listReleases)
	r.Get("/client/releases/latest", s.latestRelease)
	r.Get("/client/releases/{id}", s.releaseDetail)
}
func (s *Server) releases(r *http.Request, id string) ([]platform.ClientRelease, error) {
	channel := r.URL.Query().Get("channel")
	if channel == "" && id == "" {
		channel = "STABLE"
	}
	// 关联安装包一次性读取，避免列表按版本重复访问数据库。
	q := gorm.G[platform.ClientRelease](s.DB).Preload("Artifacts", func(p gorm.PreloadBuilder) error {
		if os := r.URL.Query().Get("os"); os != "" {
			p.Where("os=?", os)
		}
		if arch := r.URL.Query().Get("arch"); arch != "" {
			p.Where("arch=?", arch)
		}
		return nil
	}).Where("published_at IS NOT NULL")
	if channel != "" {
		q = q.Where("channel=?", channel)
	}
	if id != "" {
		q = q.Where("id=?", id)
	}
	rows, e := q.Order("published_at DESC").Limit(100).Find(r.Context())
	if e != nil {
		return nil, e
	}
	out := []platform.ClientRelease{}
	for _, row := range rows {
		if len(row.Artifacts) > 0 {
			out = append(out, row)
		}
	}
	return out, nil
}
func (s *Server) listReleases(w http.ResponseWriter, r *http.Request) {
	rows, e := s.releases(r, "")
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}
func (s *Server) latestRelease(w http.ResponseWriter, r *http.Request) {
	rows, e := s.releases(r, "")
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if len(rows) == 0 {
		s.fail(w, r, gorm.ErrRecordNotFound)
		return
	}
	reply(w, 200, rows[0])
}

func (s *Server) releaseDetail(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	rows, e := s.releases(r, id)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if len(rows) == 0 {
		s.fail(w, r, gorm.ErrRecordNotFound)
		return
	}
	reply(w, 200, rows[0])
}
