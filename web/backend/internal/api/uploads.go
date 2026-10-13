package api

import (
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/http"
	"path"
	"regexp"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

var clientVersionPattern = regexp.MustCompile(`^[0-9]+\.[0-9]+\.[0-9]+$`)

func (s *Server) uploadView(r *http.Request, u platform.Upload) (platform.Upload, error) {
	u.Method = "PUT"
	u.Headers = map[string]string{"Content-Type": "application/octet-stream"}
	u.URL = "/api/v1/uploads/" + u.ID + "/content"
	if s.Config.StorageDriver == "s3" && u.Status == "CREATED" {
		url, e := s.Storage.PresignPut(r.Context(), u.ObjectKey, u.ExpectedBytes)
		if e != nil {
			return u, e
		}
		u.URL = url
	}
	return u, nil
}
func (s *Server) newUpload(r *http.Request, tx *gorm.DB, res platform.Resource, vid *string, purpose, filename string, size int64) (platform.Upload, error) {
	u := platform.Upload{ID: uuid.NewString(), UserID: who(r).User.ID, ResourceID: res.ID, VersionID: vid, Purpose: purpose, Filename: filename, ExpectedBytes: size, ReservedBytes: size, Status: "CREATED", CreatedAt: time.Now(), ExpiresAt: time.Now().Add(15 * time.Minute)}
	u.ObjectKey = "quarantine/" + u.ID + "/" + filename
	// 条件更新即原子配额预留，不从已读取的用户快照计算可用空间。
	result := tx.WithContext(r.Context()).Exec("UPDATE users SET reserved_bytes=reserved_bytes+? WHERE id=? AND status='ACTIVE' AND email_verified AND used_bytes+reserved_bytes+?<=quota_bytes", size, u.UserID, size)
	if result.Error != nil {
		return u, result.Error
	}
	if result.RowsAffected != 1 {
		return u, ErrRule
	}
	return u, gorm.G[platform.Upload](tx).Create(r.Context(), &u)
}
func (s *Server) createVersion(w http.ResponseWriter, r *http.Request) {
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
		Version, Filename, MinimumClientVersion, TargetModelVersionID, Entrypoint string
		ExpectedBytes                                                             int64
	}
	if !decode(w, r, &in) {
		return
	}
	if len(in.Version) == 0 || len(in.Version) > 80 || in.ExpectedBytes <= 0 || in.ExpectedBytes > s.Config.MaxUploadBytes || !resource.SafeUploadFilename(in.Filename) {
		invalid(w, r, "文件名、版本或大小无效")
		return
	}
	if in.MinimumClientVersion != "" && (len(in.MinimumClientVersion) > 40 || !clientVersionPattern.MatchString(in.MinimumClientVersion)) {
		invalid(w, r, "最低客户端版本应为三段数字版本或留空")
		return
	}
	if res.Kind == "MODEL" && !strings.HasSuffix(in.Filename, ".zip") {
		invalid(w, r, "模型需要完整ZIP导出包")
		return
	}
	if (res.Kind == "MOTION" || res.Kind == "EXPRESSION") && in.TargetModelVersionID == "" {
		invalid(w, r, "动作和表情必须绑定精确模型版本")
		return
	}
	var dependency *platform.ResourceVersion
	if in.TargetModelVersionID != "" {
		if _, e := uuid.Parse(in.TargetModelVersionID); e != nil {
			invalid(w, r, "模型版本ID无效")
			return
		}
		v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND validation_status='READY'", in.TargetModelVersionID).First(r.Context())
		if e != nil {
			invalid(w, r, "目标模型版本不可用")
			return
		}
		model, e := s.accessResource(r, v.ResourceID, false)
		if e != nil || model.Kind != "MODEL" || model.Status != "ACTIVE" {
			invalid(w, r, "目标模型不可访问")
			return
		}
		dependency = &v
	}
	if in.Entrypoint != "" && !resource.SafePath(in.Entrypoint) {
		invalid(w, r, "入口路径无效")
		return
	}
	v := platform.ResourceVersion{ID: uuid.NewString(), ResourceID: id, Version: in.Version, Entrypoint: in.Entrypoint, ValidationStatus: "PENDING", CompatibilityStatus: "UNTESTED", MinimumClientVersion: in.MinimumClientVersion, ValidationReport: json.RawMessage(`{"errors":[],"warnings":[]}`), Manifest: json.RawMessage(`{}`), CreatedAt: time.Now(), Dependencies: []platform.VersionDependency{}}
	var u platform.Upload
	e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		if e := gorm.G[platform.ResourceVersion](tx).Create(r.Context(), &v); e != nil {
			return e
		}
		if dependency != nil {
			d := platform.ResourceDependency{VersionID: v.ID, TargetVersionID: dependency.ID, Relation: "TARGET_MODEL"}
			if e := gorm.G[platform.ResourceDependency](tx).Create(r.Context(), &d); e != nil {
				return e
			}
			v.Dependencies = append(v.Dependencies, platform.VersionDependency{VersionID: dependency.ID, Relation: d.Relation})
		}
		var e error
		u, e = s.newUpload(r, tx, res, &v.ID, "VERSION", in.Filename, in.ExpectedBytes)
		return e
	})
	if e == ErrRule {
		problem(w, r, 409, "QUOTA_EXCEEDED", "剩余容量不足")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	u, e = s.uploadView(r, u)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 201, map[string]interface{}{"version": v, "upload": u})
}
func (s *Server) createCover(w http.ResponseWriter, r *http.Request) {
	var in struct {
		ResourceID, Purpose, Filename string
		ExpectedBytes                 int64
	}
	if !decode(w, r, &in) {
		return
	}
	if in.Purpose != "COVER" || in.ExpectedBytes <= 0 || in.ExpectedBytes > 8<<20 || path.Base(in.Filename) != in.Filename || !resource.SafePath(in.Filename) {
		invalid(w, r, "封面文件无效")
		return
	}
	if _, e := uuid.Parse(in.ResourceID); e != nil {
		invalid(w, r, "资源ID无效")
		return
	}
	res, e := s.accessResource(r, in.ResourceID, true)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	var u platform.Upload
	e = s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var e error
		u, e = s.newUpload(r, tx, res, nil, "COVER", in.Filename, in.ExpectedBytes)
		return e
	})
	if e == ErrRule {
		problem(w, r, 409, "QUOTA_EXCEEDED", "剩余容量不足")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	u, e = s.uploadView(r, u)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 201, u)
}
func (s *Server) findUpload(r *http.Request, id string) (platform.Upload, error) {
	return gorm.G[platform.Upload](s.DB).Where("id=? AND user_id=?", id, who(r).User.ID).First(r.Context())
}
func (s *Server) uploadContent(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	if s.Config.StorageDriver != "local" {
		invalid(w, r, "请使用上传返回的对象存储地址")
		return
	}
	u, e := s.findUpload(r, id)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if u.Status != "CREATED" || time.Now().After(u.ExpiresAt) {
		problem(w, r, 409, "UPLOAD_CLOSED", "上传已关闭")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, u.ExpectedBytes+1)
	e = s.Storage.Put(r.Context(), u.ObjectKey, r.Body, u.ExpectedBytes, "application/octet-stream")
	if e != nil {
		invalid(w, r, "文件大小不符或上传失败")
		return
	}
	n, e := gorm.G[platform.Upload](s.DB).Where("id=? AND status='CREATED'", id).Update(r.Context(), "status", "UPLOADED")
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if n == 0 {
		problem(w, r, 409, "UPLOAD_CLOSED", "上传已关闭")
		return
	}
	reply(w, 204, nil)
}
func (s *Server) completeUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	key := r.Header.Get("Idempotency-Key")
	if len(key) < 8 || len(key) > 128 {
		invalid(w, r, "需要8至128字符的Idempotency-Key")
		return
	}
	var u platform.Upload
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		var e error
		u, e = gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE"}).Where("id=? AND user_id=?", id, who(r).User.ID).First(r.Context())
		if e != nil {
			return e
		}
		if u.Status == "CANCELLED" || u.Status == "EXPIRED" || u.Status == "FAILED" || time.Now().After(u.ExpiresAt) && u.Status == "CREATED" {
			return ErrRule
		}
		var old struct{ UploadID string }
		result := tx.Raw("SELECT upload_id FROM idempotency_requests WHERE user_id=? AND key=?", u.UserID, key).Scan(&old)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected > 0 && old.UploadID != id {
			return ErrRule
		}
		if e = tx.Exec("INSERT INTO idempotency_requests(user_id,key,upload_id) VALUES (?,?,?) ON CONFLICT DO NOTHING", u.UserID, key, id).Error; e != nil {
			return e
		}
		if u.Status == "READY" || u.Status == "VALIDATING" {
			return nil
		}
		if u.Status != "UPLOADED" && s.Config.StorageDriver == "local" {
			return ErrRule
		}
		payload, _ := json.Marshal(map[string]string{"uploadId": u.ID})
		dedupe := "validate:" + u.ID
		job := platform.Job{ID: uuid.NewString(), Kind: "VALIDATE", Payload: payload, Status: "QUEUED", RunAt: time.Now(), CreatedAt: time.Now(), DedupeKey: &dedupe}
		if e = gorm.G[platform.Job](tx, clause.OnConflict{DoNothing: true}).Create(r.Context(), &job); e != nil {
			return e
		}
		u.Status = "VALIDATING"
		if _, e = gorm.G[platform.Upload](tx).Where("id=?", id).Update(r.Context(), "status", u.Status); e != nil {
			return e
		}
		if u.VersionID != nil {
			_, e = gorm.G[platform.ResourceVersion](tx).Where("id=?", *u.VersionID).Update(r.Context(), "validation_status", "VALIDATING")
		}
		return e
	})
	if e == ErrRule {
		problem(w, r, 409, "UPLOAD_CONFLICT", "上传状态或幂等键冲突")
		return
	}
	if e != nil {
		s.fail(w, r, e)
		return
	}
	u, e = s.uploadView(r, u)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 202, u)
}
func (s *Server) getUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	u, e := s.findUpload(r, id)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	u, e = s.uploadView(r, u)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, u)
}
func (s *Server) listUploads(w http.ResponseWriter, r *http.Request) {
	rows, e := gorm.G[platform.Upload](s.DB).Where("user_id=?", who(r).User.ID).Order("created_at DESC").Limit(100).Find(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	for i := range rows {
		rows[i], e = s.uploadView(r, rows[i])
		if e != nil {
			s.fail(w, r, e)
			return
		}
	}
	reply(w, 200, rows)
}
func (s *Server) cancelUpload(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	e := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		u, e := gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE"}).Where("id=? AND user_id=?", id, who(r).User.ID).First(r.Context())
		if e != nil {
			return e
		}
		if u.Settled {
			return nil
		}
		if e = resource.QueueCleanup(r.Context(), tx, u.ID, []string{u.ObjectKey}); e != nil {
			return e
		}
		if e = tx.Exec("UPDATE users SET reserved_bytes=reserved_bytes-? WHERE id=?", u.ReservedBytes, u.UserID).Error; e != nil {
			return e
		}
		if e = tx.Model(&platform.Upload{}).Where("id=?", id).Updates(map[string]interface{}{"status": "CANCELLED", "settled": true}).Error; e != nil {
			return e
		}
		if u.VersionID != nil {
			report := fmt.Sprintf(`{"errors":[%q],"warnings":[]}`, "上传已取消")
			return tx.Model(&platform.ResourceVersion{}).Where("id=?", *u.VersionID).Updates(map[string]interface{}{"validation_status": "FAILED", "validation_report": report}).Error
		}
		return nil
	})
	if e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 204, nil)
}
