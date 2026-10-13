package api

import (
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

// 删除无依赖的资源与其版本；审计保留，物理对象交持久化清理任务处理。
func (s *Server) deleteResource(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	if _, e := s.accessResource(r, id, true); e != nil {
		s.fail(w, r, e)
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		res, e := gorm.G[platform.Resource](tx, clause.Locking{Strength: "UPDATE"}).Where("id=? AND owner_id=?", id, who(r).User.ID).First(r.Context())
		if e != nil {
			return e
		}
		var refs int64
		if e = tx.Raw("SELECT count(*) FROM resource_dependencies d JOIN resource_versions v ON v.id=d.target_version_id WHERE v.resource_id=?", id).Scan(&refs).Error; e != nil {
			return e
		}
		if refs > 0 {
			return ErrRule
		}
		if e = tx.Model(&platform.UserLibrary{}).Where("resource_id=? AND user_id<>?", id, res.OwnerID).Count(&refs).Error; e != nil {
			return e
		}
		if refs > 0 {
			return ErrRule
		}
		if e = tx.Model(&platform.Upload{}).Where("resource_id=? AND NOT settled", id).Count(&refs).Error; e != nil {
			return e
		}
		if refs > 0 {
			return ErrRule
		}
		versions, e := gorm.G[platform.ResourceVersion](tx).Where("resource_id=?", id).Find(r.Context())
		if e != nil {
			return e
		}
		keys := []string{}
		usage := res.CoverBytes
		if res.CoverKey != nil {
			keys = append(keys, *res.CoverKey)
		}
		for _, v := range versions {
			usage += v.PackageBytes
			if v.PackageKey != "" {
				keys = append(keys, v.PackageKey)
			}
		}
		uploads, e := gorm.G[platform.Upload](tx).Where("resource_id=?", id).Find(r.Context())
		if e != nil {
			return e
		}
		for _, u := range uploads {
			keys = append(keys, u.ObjectKey)
		}
		// 固定顺序解除FK；目标模型被动作/表情引用时此前已经拒绝。
		for _, statement := range []string{"DELETE FROM user_library WHERE resource_id=?", "DELETE FROM download_tickets WHERE resource_id=?", "DELETE FROM idempotency_requests WHERE upload_id IN (SELECT id FROM uploads WHERE resource_id=?)", "DELETE FROM uploads WHERE resource_id=?", "UPDATE resources SET current_version_id=NULL WHERE id=?", "DELETE FROM resource_dependencies WHERE version_id IN (SELECT id FROM resource_versions WHERE resource_id=?)", "DELETE FROM resource_files WHERE version_id IN (SELECT id FROM resource_versions WHERE resource_id=?)", "DELETE FROM resource_versions WHERE resource_id=?", "DELETE FROM resources WHERE id=?"} {
			if e = tx.Exec(statement, id).Error; e != nil {
				return e
			}
		}
		if e = tx.Exec("UPDATE users SET used_bytes=used_bytes-? WHERE id=?", usage, res.OwnerID).Error; e != nil {
			return e
		}
		if e = resource.QueueCleanup(r.Context(), tx, "resource:"+id, keys); e != nil {
			return e
		}
		return s.audit(r.Context(), tx, res.OwnerID, "RESOURCE_DELETE", id)
	})
	if e == ErrRule {
		problem(w, r, 409, "RESOURCE_IN_USE", "资源仍被引用或正在上传")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
