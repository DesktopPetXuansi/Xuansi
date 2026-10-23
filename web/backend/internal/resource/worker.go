package resource

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"time"
	"xuansi/web/backend/internal/platform"
)

type Worker struct {
	DB                 *gorm.DB
	Storage            platform.ObjectStorage
	Config             platform.Config
	Log                *slog.Logger
	Owner              string
	FeedbackHTTPClient *http.Client
}

// Run 单进程顺序处理；数据库租约允许多个独立进程安全扩展。
func (w *Worker) Run(ctx context.Context) error {
	if w.Owner == "" {
		w.Owner = uuid.NewString()
	}
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if e := w.Tick(ctx); e != nil {
			w.Log.Error("任务轮询失败", "error", e)
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}
func (w *Worker) Tick(ctx context.Context) error {
	if e := w.expire(ctx); e != nil {
		return e
	}
	job, e := w.claim(ctx)
	if errors.Is(e, gorm.ErrRecordNotFound) {
		return nil
	}
	if e != nil {
		return e
	}
	workCtx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	switch job.Kind {
	case "MAIL":
		e = w.sendMail(workCtx, job.Payload)
	case "VALIDATE":
		e = w.validate(workCtx, job.Payload)
	case "CLEANUP":
		e = w.cleanup(workCtx, job.Payload)
	case "FEEDBACK_GITHUB":
		e = w.deliverFeedback(workCtx, job.Payload)
	default:
		e = fmt.Errorf("未知任务")
	}
	var channelWait *feedbackChannelWait
	if job.Kind == "FEEDBACK_GITHUB" && errors.As(e, &channelWait) {
		// 仅推迟这次调度，保留真实远端投递的重试次数。
		w.Log.Info("GitHub 反馈渠道等待", "jobId", job.ID)
		return w.DB.WithContext(ctx).Model(&platform.Job{}).Where("id=? AND lease_owner=?", job.ID, w.Owner).Updates(map[string]interface{}{
			"status": "QUEUED", "attempts": job.Attempts - 1, "lease_until": nil, "lease_owner": nil, "run_at": channelWait.until,
		}).Error
	}
	status := "DONE"
	var message *string
	if e != nil {
		safe := "任务执行失败，请查看校验报告"
		message = &safe
		status = "QUEUED"
		if job.Attempts >= 5 {
			status = "FAILED"
			if job.Kind == "CLEANUP" {
				status = "QUEUED"
			}
			if job.Kind == "VALIDATE" {
				var input struct {
					UploadID string `json:"uploadId"`
				}
				if json.Unmarshal(job.Payload, &input) == nil {
					u, findErr := gorm.G[platform.Upload](w.DB).Where("id=?", input.UploadID).First(ctx)
					if findErr == nil {
						_ = w.reject(ctx, u, fmt.Errorf("校验服务连续失败，请重新上传"))
					}
				}
			}
		}
		w.Log.Warn("后台任务失败", "jobId", job.ID, "kind", job.Kind, "attempt", job.Attempts, "error", e)
	} else {
		w.Log.Info("后台任务完成", "jobId", job.ID, "kind", job.Kind)
	}
	delay := job.Attempts * job.Attempts
	if delay > 3600 {
		delay = 3600
	}
	retryDelay := time.Duration(delay) * time.Second
	if job.Kind == "FEEDBACK_GITHUB" && e != nil {
		var safe string
		status, retryDelay, safe = feedbackRetry(e, job.Attempts)
		message = &safe
	}
	fields := map[string]interface{}{"status": status, "lease_until": nil, "lease_owner": nil, "last_error": message, "run_at": time.Now().Add(retryDelay)}
	if job.Kind == "MAIL" && (status == "DONE" || status == "FAILED") {
		fields["payload"] = "{}"
	}
	return w.DB.WithContext(ctx).Model(&platform.Job{}).Where("id=? AND lease_owner=?", job.ID, w.Owner).Updates(fields).Error
}
func (w *Worker) claim(ctx context.Context) (platform.Job, error) {
	var job platform.Job
	e := w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var e error
		query := gorm.G[platform.Job](tx, clause.Locking{Strength: "UPDATE", Options: "SKIP LOCKED"}).Where("(status='QUEUED' AND run_at<=?) OR (status='RUNNING' AND lease_until<?)", time.Now(), time.Now())
		if w.Config.MailDeliveryDisabled {
			// 领取前排除邮件，保留原状态、租约和重试次数；其他任务照常调度。
			query = query.Where("kind <> ?", "MAIL")
		}
		job, e = query.Order("run_at ASC").First(ctx)
		if e != nil {
			return e
		}
		until := time.Now().Add(3 * time.Minute)
		job.Attempts++
		return tx.Model(&platform.Job{}).Where("id=?", job.ID).Updates(map[string]interface{}{"status": "RUNNING", "attempts": job.Attempts, "lease_until": until, "lease_owner": w.Owner}).Error
	})
	return job, e
}
func (w *Worker) expire(ctx context.Context) error {
	return w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		rows, e := gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE", Options: "SKIP LOCKED"}).Where("expires_at<? AND status IN ('CREATED','UPLOADED') AND NOT settled", time.Now()).Limit(100).Find(ctx)
		if e != nil {
			return e
		}
		for _, u := range rows {
			if e = settleFailure(ctx, tx, u, "EXPIRED", "上传已过期"); e != nil {
				return e
			}
		}
		return nil
	})
}
func settleFailure(ctx context.Context, tx *gorm.DB, u platform.Upload, status, message string) error {
	if u.Settled {
		return nil
	}
	if e := QueueCleanup(ctx, tx, u.ID, []string{u.ObjectKey}); e != nil {
		return e
	}
	if e := tx.Exec("UPDATE users SET reserved_bytes=reserved_bytes-? WHERE id=?", u.ReservedBytes, u.UserID).Error; e != nil {
		return e
	}
	if e := tx.Model(&platform.Upload{}).Where("id=?", u.ID).Updates(map[string]interface{}{"status": status, "settled": true, "error_code": "VALIDATION_FAILED"}).Error; e != nil {
		return e
	}
	if u.VersionID != nil {
		report, _ := json.Marshal(map[string][]string{"errors": {message}, "warnings": {}})
		return tx.Model(&platform.ResourceVersion{}).Where("id=?", *u.VersionID).Updates(map[string]interface{}{"validation_status": "FAILED", "validation_report": string(report)}).Error
	}
	return nil
}
func (w *Worker) validate(ctx context.Context, payload json.RawMessage) error {
	var in struct {
		UploadID string `json:"uploadId"`
	}
	if e := json.Unmarshal(payload, &in); e != nil {
		return e
	}
	u, e := gorm.G[platform.Upload](w.DB).Where("id=?", in.UploadID).First(ctx)
	if e != nil {
		return e
	}
	if u.Settled {
		return nil
	}
	res, e := gorm.G[platform.Resource](w.DB).Where("id=?", u.ResourceID).First(ctx)
	if e != nil {
		return e
	}
	input, e := w.snapshot(ctx, u)
	if e != nil {
		return w.reject(ctx, u, e)
	}
	defer os.Remove(input)
	if u.Purpose == "COVER" {
		return w.processCover(ctx, u, input)
	}
	v, e := gorm.G[platform.ResourceVersion](w.DB).Where("id=?", *u.VersionID).First(ctx)
	if e != nil {
		return e
	}
	entry := v.Entrypoint
	if entry == "" && res.Kind != "MODEL" {
		entry = u.Filename
	}
	pkg, e := BuildPackage(input, res.Kind, entry, res.ID, v.ID, v.Version, v.MinimumClientVersion)
	if e != nil {
		return w.reject(ctx, u, e)
	}
	defer os.Remove(pkg.Path)
	ds, e := gorm.G[platform.ResourceDependency](w.DB).Where("version_id=?", v.ID).Find(ctx)
	if e != nil {
		return e
	}
	for _, d := range ds {
		target, e := gorm.G[platform.ResourceVersion](w.DB).Where("id=? AND validation_status='READY'", d.TargetVersionID).First(ctx)
		if e != nil {
			return w.reject(ctx, u, fmt.Errorf("目标模型版本不可用"))
		}
		if _, e := gorm.G[platform.Resource](w.DB).Where("id=? AND status='ACTIVE'", target.ResourceID).First(ctx); e != nil {
			return w.reject(ctx, u, fmt.Errorf("目标模型已停用"))
		}
		pkg.Manifest.Dependencies = append(pkg.Manifest.Dependencies, Dependency{ResourceID: target.ResourceID, VersionID: target.ID, Kind: "MODEL", Relation: d.Relation})
	}
	key := "packages/" + v.ID + "/" + pkg.SHA256 + ".zip"
	if e = QueueArtifactCleanup(ctx, w.DB, u, key); e != nil {
		return e
	}
	f, e := os.Open(pkg.Path)
	if e != nil {
		return e
	}
	e = w.Storage.Put(ctx, key, f, pkg.Bytes, "application/zip")
	_ = f.Close()
	if e != nil {
		return e
	}
	manifest, _ := json.Marshal(pkg.Manifest)
	e = w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		current, e := gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE"}).Where("id=?", u.ID).First(ctx)
		if e != nil {
			return e
		}
		if current.Settled {
			return nil
		}
		if e = QueueCleanup(ctx, tx, u.ID, []string{u.ObjectKey}); e != nil {
			return e
		}
		user, e := gorm.G[platform.User](tx, clause.Locking{Strength: "UPDATE"}).Where("id=?", u.UserID).First(ctx)
		if e != nil {
			return e
		}
		if user.Status != "ACTIVE" || user.UsedBytes+user.ReservedBytes-u.ReservedBytes+pkg.Bytes > user.QuotaBytes {
			return settleFailure(ctx, tx, current, "FAILED", "用户停用或规范包容量超出配额")
		}
		if e = tx.Exec("UPDATE users SET reserved_bytes=reserved_bytes-?,used_bytes=used_bytes+? WHERE id=?", u.ReservedBytes, pkg.Bytes, u.UserID).Error; e != nil {
			return e
		}
		if e = tx.Model(&platform.Upload{}).Where("id=?", u.ID).Updates(map[string]interface{}{"status": "READY", "settled": true}).Error; e != nil {
			return e
		}
		if e = tx.Model(&platform.ResourceVersion{}).Where("id=?", v.ID).Updates(map[string]interface{}{"validation_status": "READY", "entrypoint": pkg.Manifest.Entrypoint, "package_key": key, "package_bytes": pkg.Bytes, "package_sha256": pkg.SHA256, "manifest": string(manifest), "validation_report": `{"errors":[],"warnings":["结构校验通过，实际Live2D运行兼容性需客户端试载"]}`}).Error; e != nil {
			return e
		}
		for _, f := range pkg.Manifest.Files {
			row := platform.ResourceFile{VersionID: v.ID, Path: f.Path, Bytes: f.Bytes, SHA256: f.SHA256}
			if e = gorm.G[platform.ResourceFile](tx, clause.OnConflict{DoNothing: true}).Create(ctx, &row); e != nil {
				return e
			}
		}
		return tx.Model(&platform.Resource{}).Where("id=? AND current_version_id IS NULL", res.ID).Updates(map[string]interface{}{"current_version_id": v.ID, "updated_at": time.Now()}).Error
	})
	if e != nil {
		return e
	}
	return w.Storage.Delete(ctx, u.ObjectKey)
}
func (w *Worker) snapshot(ctx context.Context, u platform.Upload) (string, error) {
	r, e := w.Storage.Open(ctx, u.ObjectKey)
	if e != nil {
		return "", e
	}
	defer r.Close()
	file, e := os.CreateTemp("", "xuansi-quarantine-*"+filepath.Ext(u.Filename))
	if e != nil {
		return "", e
	}
	name := file.Name()
	n, e := io.Copy(file, io.LimitReader(r, u.ExpectedBytes+1))
	closeErr := file.Close()
	if e != nil || closeErr != nil || n != u.ExpectedBytes {
		_ = os.Remove(name)
		return "", fmt.Errorf("上传大小不符或对象读取失败")
	}
	return name, nil
}
func (w *Worker) reject(ctx context.Context, u platform.Upload, cause error) error {
	w.Log.Info("资源校验拒绝", "uploadId", u.ID, "reason", cause.Error())
	e := w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		current, e := gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE"}).Where("id=?", u.ID).First(ctx)
		if e != nil {
			return e
		}
		return settleFailure(ctx, tx, current, "FAILED", cause.Error())
	})
	if e == nil {
		_ = w.Storage.Delete(ctx, u.ObjectKey)
	}
	return e
}
