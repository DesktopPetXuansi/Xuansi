package resource

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"time"
	"xuansi/web/backend/internal/platform"
)

type cleanupPayload struct {
	Keys     []string `json:"keys"`
	UploadID string   `json:"uploadId,omitempty"`
}

// 清理任务与业务状态一起提交，存储暂时失败时仍能重试。
func QueueCleanup(ctx context.Context, tx *gorm.DB, key string, objects []string) error {
	if len(objects) == 0 {
		return nil
	}
	payload, e := json.Marshal(cleanupPayload{Keys: objects})
	if e != nil {
		return e
	}
	dedupe := "cleanup:" + key
	return gorm.G[platform.Job](tx, clause.OnConflict{DoNothing: true}).Create(ctx, &platform.Job{ID: uuid.NewString(), Kind: "CLEANUP", Payload: payload, Status: "QUEUED", RunAt: time.Now(), CreatedAt: time.Now(), DedupeKey: &dedupe})
}

// 写对象之前登记回收责任，进程退出、事务失败和取消均不会丢失产物键。
func QueueArtifactCleanup(ctx context.Context, db *gorm.DB, u platform.Upload, key string) error {
	payload, e := json.Marshal(cleanupPayload{Keys: []string{key}, UploadID: u.ID})
	if e != nil {
		return e
	}
	dedupe := "cleanup:artifact:" + key
	return gorm.G[platform.Job](db, clause.OnConflict{DoNothing: true}).Create(ctx, &platform.Job{ID: uuid.NewString(), Kind: "CLEANUP", Payload: payload, Status: "QUEUED", RunAt: time.Now().Add(3 * time.Minute), CreatedAt: time.Now(), DedupeKey: &dedupe})
}

func (w *Worker) cleanup(ctx context.Context, payload json.RawMessage) error {
	var in cleanupPayload
	if e := json.Unmarshal(payload, &in); e != nil {
		return e
	}
	if in.UploadID != "" {
		var working int64
		if e := w.DB.WithContext(ctx).Model(&platform.Upload{}).Where("id=? AND NOT settled", in.UploadID).Count(&working).Error; e != nil {
			return e
		}
		if working > 0 {
			return fmt.Errorf("上传尚未结算，延后回收")
		}
		if e := w.DB.WithContext(ctx).Model(&platform.Job{}).Where("dedupe_key=? AND status='RUNNING' AND lease_until>?", "validate:"+in.UploadID, time.Now()).Count(&working).Error; e != nil {
			return e
		}
		if working > 0 {
			return fmt.Errorf("校验仍持有租约，延后回收")
		}
	}
	for _, key := range in.Keys {
		if key != "" {
			// 未发布产物才删除；同内容重试和旧封面清理不能损坏已引用对象。
			var refs int64
			if e := w.DB.WithContext(ctx).Raw("SELECT (SELECT count(*) FROM resource_versions WHERE package_key=?) + (SELECT count(*) FROM resources WHERE cover_key=?)", key, key).Scan(&refs).Error; e != nil {
				return e
			}
			if refs > 0 {
				continue
			}
			if e := w.Storage.Delete(ctx, key); e != nil {
				return e
			}
		}
	}
	return nil
}
