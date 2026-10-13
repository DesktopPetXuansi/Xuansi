package api

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"net/http"
	"net/url"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) adminRoutes(r chi.Router) {
	r.Route("/admin", func(r chi.Router) {
		r.Use(admin)
		r.Get("/users", s.adminUsers)
		r.Patch("/users/{id}", s.adminUserStatus)
		r.Get("/resources", s.adminResources)
		r.Patch("/resources/{id}", s.adminResourceStatus)
		r.Post("/resources/{id}/publications", s.publishResource)
		r.Get("/client-releases", s.adminReleases)
		r.Post("/client-releases", s.createRelease)
		r.Patch("/client-releases/{id}", s.patchRelease)
		r.Post("/client-releases/{id}/publications", s.publishRelease)
		r.Get("/jobs", s.adminJobs)
		r.Get("/audit-logs", s.adminAudit)
	})
}
func (s *Server) adminUsers(w http.ResponseWriter, r *http.Request) {
	limit, _ := page(r)
	rows, e := gorm.G[platform.User](s.DB).Order("created_at DESC").Limit(limit).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	out := []platform.UserView{}
	for _, u := range rows {
		out = append(out, u.View())
	}
	reply(w, 200, out)
}
func (s *Server) adminUserStatus(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	var in struct{ Status string }
	if !decode(w, r, &in) {
		return
	}
	if in.Status != "ACTIVE" && in.Status != "DISABLED" {
		invalid(w, r, "状态无效")
		return
	}
	if id == who(r).User.ID && in.Status == "DISABLED" {
		problem(w, r, 409, "SELF_DISABLE", "不能停用当前管理员")
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		n, e := gorm.G[platform.User](tx).Where("id=?", id).Update(r.Context(), "status", in.Status)
		if e != nil {
			return e
		}
		if n == 0 {
			return gorm.ErrRecordNotFound
		}
		if in.Status == "DISABLED" {
			if e = revokeUser(r.Context(), tx, id); e != nil {
				return e
			}
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "USER_STATUS_"+in.Status, id)
	})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) adminResources(w http.ResponseWriter, r *http.Request) {
	limit, _ := page(r)
	rows, e := gorm.G[platform.Resource](s.DB).Order("created_at DESC").Limit(limit).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	for i := range rows {
		if rows[i].CoverKey != nil {
			u := "/api/v1/resources/" + rows[i].ID + "/cover"
			rows[i].CoverURL = &u
		}
	}
	reply(w, 200, rows)
}
func (s *Server) adminResourceStatus(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	var in struct{ Status string }
	if !decode(w, r, &in) {
		return
	}
	if in.Status != "ACTIVE" && in.Status != "HIDDEN" && in.Status != "DISABLED" {
		invalid(w, r, "状态无效")
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		n, e := gorm.G[platform.Resource](tx).Where("id=?", id).Update(r.Context(), "status", in.Status)
		if e != nil {
			return e
		}
		if n == 0 {
			return gorm.ErrRecordNotFound
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "RESOURCE_STATUS_"+in.Status, id)
	})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) publishResource(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	var in struct{ VersionID string }
	if !decode(w, r, &in) {
		return
	}
	if _, e := uuid.Parse(in.VersionID); e != nil {
		invalid(w, r, "版本ID无效")
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		v, e := gorm.G[platform.ResourceVersion](tx).Where("id=? AND resource_id=? AND validation_status='READY'", in.VersionID, id).First(r.Context())
		if e != nil {
			return e
		}
		res, e := gorm.G[platform.Resource](tx).Where("id=?", id).First(r.Context())
		if e != nil {
			return e
		}
		if strings.TrimSpace(res.License) == "" || strings.TrimSpace(res.Author) == "" {
			return ErrRule
		}
		var privateDeps int64
		if e = tx.Raw("SELECT count(*) FROM resource_dependencies d JOIN resource_versions v ON v.id=d.target_version_id JOIN resources r ON r.id=v.resource_id WHERE d.version_id=? AND (r.visibility<>'PUBLIC' OR r.status<>'ACTIVE')", v.ID).Scan(&privateDeps).Error; e != nil {
			return e
		}
		if privateDeps > 0 {
			return ErrRule
		}
		if e = tx.Model(&platform.Resource{}).Where("id=?", id).Updates(map[string]interface{}{"visibility": "PUBLIC", "status": "ACTIVE", "current_version_id": v.ID, "updated_at": time.Now()}).Error; e != nil {
			return e
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "RESOURCE_PUBLISH", id)
	})
	if e == ErrRule {
		problem(w, r, 409, "PUBLICATION_BLOCKED", "需要作者、许可及公开可用的依赖模型")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, res)
}
func (s *Server) adminReleases(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.ClientRelease](s.DB).Preload("Artifacts", nil).Order("created_at DESC").Limit(100).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}

type releaseInput struct {
	Version, Channel, SourceCommit, ReleaseNotes string
	Artifacts                                    []struct {
		OS, Arch, DistributionType, DownloadURL, SHA256 string
		Bytes                                           int64
		SystemRequirements                              []string
	}
}

func validRelease(in releaseInput) error {
	if len(in.Version) == 0 || len(in.Version) > 80 || in.Channel != "STABLE" && in.Channel != "BETA" || len(in.SourceCommit) < 7 || len(in.SourceCommit) > 64 || len(in.ReleaseNotes) > 50000 || len(in.Artifacts) == 0 || len(in.Artifacts) > 10 {
		return fmt.Errorf("发布元数据无效")
	}
	for _, a := range in.Artifacts {
		u, e := url.Parse(a.DownloadURL)
		hash, he := hex.DecodeString(a.SHA256)
		if e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || he != nil || len(hash) != 32 || a.Bytes <= 0 || a.OS != "windows" || a.Arch != "x64" || a.DistributionType == "" || len(a.SystemRequirements) == 0 {
			return fmt.Errorf("安装包元数据无效")
		}
	}
	return nil
}
func (s *Server) createRelease(w http.ResponseWriter, r *http.Request) {
	var in releaseInput
	if !decode(w, r, &in) {
		return
	}
	if e := validRelease(in); e != nil {
		invalid(w, r, e.Error())
		return
	}
	release := platform.ClientRelease{ID: uuid.NewString(), Version: in.Version, Channel: in.Channel, SourceCommit: in.SourceCommit, ReleaseNotes: in.ReleaseNotes, CreatedAt: time.Now(), Artifacts: []platform.ReleaseArtifact{}}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if e := gorm.G[platform.ClientRelease](tx).Create(r.Context(), &release); e != nil {
			return e
		}
		for _, a := range in.Artifacts {
			requirements, _ := json.Marshal(a.SystemRequirements)
			row := platform.ReleaseArtifact{ID: uuid.NewString(), ReleaseID: release.ID, OS: a.OS, Arch: a.Arch, DistributionType: a.DistributionType, DownloadURL: a.DownloadURL, SHA256: a.SHA256, Bytes: a.Bytes, SystemRequirements: requirements}
			if e := gorm.G[platform.ReleaseArtifact](tx).Create(r.Context(), &row); e != nil {
				return e
			}
			release.Artifacts = append(release.Artifacts, row)
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "RELEASE_CREATE", release.ID)
	})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 201, release)
}
func (s *Server) patchRelease(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	var in struct{ ReleaseNotes string }
	if !decode(w, r, &in) {
		return
	}
	if len(in.ReleaseNotes) > 50000 {
		invalid(w, r, "更新说明过长")
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		n, e := gorm.G[platform.ClientRelease](tx).Where("id=? AND published_at IS NULL", id).Update(r.Context(), "release_notes", in.ReleaseNotes)
		if e != nil {
			return e
		}
		if n == 0 {
			return ErrRule
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "RELEASE_NOTES_UPDATE", id)
	})
	if e == ErrRule {
		problem(w, r, 409, "RELEASE_IMMUTABLE", "已发布版本不可修改")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) publishRelease(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var n int64
		if e := tx.Model(&platform.ReleaseArtifact{}).Where("release_id=?", id).Count(&n).Error; e != nil {
			return e
		}
		if n == 0 {
			return ErrRule
		}
		result := tx.Model(&platform.ClientRelease{}).Where("id=? AND published_at IS NULL", id).Update("published_at", time.Now())
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			return ErrRule
		}
		return s.audit(r.Context(), tx, who(r).User.ID, "RELEASE_PUBLISH", id)
	})
	if e == ErrRule {
		problem(w, r, 409, "RELEASE_CONFLICT", "缺少安装包或版本已发布")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
func (s *Server) adminJobs(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.Job](s.DB).Order("created_at DESC").Limit(100).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}
func (s *Server) adminAudit(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.AuditLog](s.DB).Order("created_at DESC").Limit(100).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}
