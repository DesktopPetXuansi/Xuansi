package resource

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"image"
	"image/png"
	"os"
	"time"
	"xuansi/web/backend/internal/platform"
)

// 封面统一重编码为PNG，去掉嵌入数据并限制像素容量。
func (w *Worker) processCover(ctx context.Context, u platform.Upload, input string) error {
	b, e := os.ReadFile(input)
	if e != nil {
		return e
	}
	cfg, _, e := image.DecodeConfig(bytes.NewReader(b))
	if e != nil || cfg.Width <= 0 || cfg.Height <= 0 || int64(cfg.Width)*int64(cfg.Height) > 16_000_000 {
		return w.reject(ctx, u, fmt.Errorf("封面格式或尺寸无效"))
	}
	img, _, e := image.Decode(bytes.NewReader(b))
	if e != nil {
		return w.reject(ctx, u, e)
	}
	var out bytes.Buffer
	if e = png.Encode(&out, img); e != nil {
		return e
	}
	hash := sha256.Sum256(out.Bytes())
	key := "covers/" + u.ResourceID + "/" + u.ID + "/" + hex.EncodeToString(hash[:]) + ".png"
	if e = QueueArtifactCleanup(ctx, w.DB, u, key); e != nil {
		return e
	}
	if e = w.Storage.Put(ctx, key, bytes.NewReader(out.Bytes()), int64(out.Len()), "image/png"); e != nil {
		return e
	}
	e = w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		current, e := gorm.G[platform.Upload](tx, clause.Locking{Strength: "UPDATE"}).Where("id=?", u.ID).First(ctx)
		if e != nil {
			return e
		}
		if current.Settled {
			return nil
		}
		res, e := gorm.G[platform.Resource](tx, clause.Locking{Strength: "UPDATE"}).Where("id=?", u.ResourceID).First(ctx)
		if e != nil {
			return e
		}
		if res.CoverKey != nil && *res.CoverKey != key {
			if e = QueueCleanup(ctx, tx, "old-cover:"+u.ID, []string{*res.CoverKey}); e != nil {
				return e
			}
		}
		result := tx.Exec("UPDATE users SET reserved_bytes=reserved_bytes-?,used_bytes=used_bytes-?+? WHERE id=? AND status='ACTIVE' AND used_bytes+reserved_bytes-?-?+?<=quota_bytes", u.ReservedBytes, res.CoverBytes, out.Len(), u.UserID, u.ReservedBytes, res.CoverBytes, out.Len())
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected != 1 {
			return settleFailure(ctx, tx, current, "FAILED", "封面容量超出配额")
		}
		if e = tx.Model(&platform.Upload{}).Where("id=?", u.ID).Updates(map[string]interface{}{"status": "READY", "settled": true}).Error; e != nil {
			return e
		}
		return tx.Model(&platform.Resource{}).Where("id=?", u.ResourceID).Updates(map[string]interface{}{"cover_key": key, "cover_bytes": out.Len(), "updated_at": time.Now()}).Error
	})
	if e != nil {
		return e
	}
	return w.Storage.Delete(ctx, u.ObjectKey)
}
