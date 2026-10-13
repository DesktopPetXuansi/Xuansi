package api

import (
	"gorm.io/gorm"
	"net/http"
	"xuansi/web/backend/internal/platform"
)

// 版本读取与清单服务独立于资源资料编辑，方便维护访问权限和依赖契约。
func (s *Server) versions(r *http.Request, id string) ([]platform.ResourceVersion, error) {
	if _, e := s.accessResource(r, id, false); e != nil {
		return nil, e
	}
	rows, e := gorm.G[platform.ResourceVersion](s.DB).Where("resource_id=?", id).Order("created_at DESC").Find(r.Context())
	if e != nil {
		return nil, e
	}
	return s.versionDependencies(r, rows)
}

// 版本依赖批量加载，单条详情也复用此映射，空依赖始终返回 JSON 数组。
func (s *Server) versionDependencies(r *http.Request, rows []platform.ResourceVersion) ([]platform.ResourceVersion, error) {
	if len(rows) == 0 {
		return rows, nil
	}
	ids := make([]string, len(rows))
	positions := make(map[string]int, len(rows))
	for i := range rows {
		ids[i], positions[rows[i].ID] = rows[i].ID, i
		rows[i].Dependencies = []platform.VersionDependency{}
	}
	dependencies, e := gorm.G[platform.ResourceDependency](s.DB).Where("version_id IN ?", ids).Find(r.Context())
	if e != nil {
		return nil, e
	}
	for _, dependency := range dependencies {
		i := positions[dependency.VersionID]
		rows[i].Dependencies = append(rows[i].Dependencies, platform.VersionDependency{VersionID: dependency.TargetVersionID, Relation: dependency.Relation})
	}
	return rows, nil
}
func (s *Server) listVersions(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	rows, e := s.versions(r, id)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows)
}
func (s *Server) getVersion(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	vid, ok := validID(w, r, "versionId")
	if !ok {
		return
	}
	if _, e := s.accessResource(r, id, false); e != nil {
		s.fail(w, r, e)
		return
	}
	version, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND resource_id=?", vid, id).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	rows, e := s.versionDependencies(r, []platform.ResourceVersion{version})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, rows[0])
}
func (s *Server) manifest(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	vid, ok := validID(w, r, "versionId")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if res.Status != "ACTIVE" {
		problem(w, r, 403, "RESOURCE_DISABLED", "资源不可用")
		return
	}
	v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND resource_id=? AND validation_status='READY'", vid, id).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, v.Manifest)
}
