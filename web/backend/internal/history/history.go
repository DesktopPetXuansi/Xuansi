// Package history 保存最少的形象使用和下载快照，不接收客户端凭据或文件路径。
package history

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"strings"
	"time"
	"unicode/utf8"
)

type Entry struct {
	ID                string    `json:"id"`
	UserID            string    `json:"-"`
	Kind              string    `json:"kind"`
	AppearanceKind    *string   `json:"appearanceKind"`
	ResourceID        *string   `json:"resourceId"`
	ResourceVersionID *string   `json:"resourceVersionId"`
	Name              string    `json:"name"`
	Version           *string   `json:"version"`
	OccurredAt        time.Time `json:"occurredAt"`
	DeviceLabel       string    `json:"deviceLabel"`
	RequestHash       string    `json:"-"`
	Available         bool      `json:"available" gorm:"-"`
}

func (Entry) TableName() string { return "personal_history" }

type Input struct {
	Kind              string    `json:"kind"`
	AppearanceKind    string    `json:"appearanceKind"`
	ResourceID        *string   `json:"resourceId"`
	ResourceVersionID *string   `json:"resourceVersionId"`
	Name              string    `json:"name"`
	OccurredAt        time.Time `json:"occurredAt"`
	DeviceLabel       string    `json:"deviceLabel"`
}

// Validate 仅接受实际形象使用，网络资源必须成对提供可规范化的 UUID。
func (in Input) Validate(now time.Time) bool {
	if in.Kind != "APPEARANCE" || !validAppearance(in.AppearanceKind) || strings.TrimSpace(in.Name) == "" || utf8.RuneCountInString(in.Name) > 120 || utf8.RuneCountInString(in.DeviceLabel) > 80 || in.OccurredAt.IsZero() || in.OccurredAt.After(now.Add(5*time.Minute)) {
		return false
	}
	if (in.ResourceID == nil) != (in.ResourceVersionID == nil) {
		return false
	}
	if in.ResourceID != nil {
		if in.AppearanceKind == "DEFAULT" {
			return false
		}
		for _, id := range []*string{in.ResourceID, in.ResourceVersionID} {
			parsed, e := uuid.Parse(*id)
			if e != nil || parsed.String() != *id {
				return false
			}
		}
	}
	return true
}
func validAppearance(kind string) bool {
	return kind == "DEFAULT" || kind == "MODEL" || kind == "IMAGE" || kind == "ANIMATION"
}
func (in Input) Entry(user, id string) Entry {
	body, _ := json.Marshal(in)
	sum := sha256.Sum256(body)
	return Entry{ID: id, UserID: user, Kind: in.Kind, AppearanceKind: &in.AppearanceKind, ResourceID: in.ResourceID, ResourceVersionID: in.ResourceVersionID, Name: in.Name, OccurredAt: in.OccurredAt, DeviceLabel: in.DeviceLabel, RequestHash: hex.EncodeToString(sum[:])}
}

var ErrConflict = errors.New("历史请求内容冲突")

// Put 由数据库唯一键处理并发重试，摘要保留原始请求语义，不受资源更名影响。
func Put(ctx context.Context, db *gorm.DB, row Entry) error {
	result := gorm.WithResult()
	if e := gorm.G[Entry](db, result, clause.OnConflict{DoNothing: true}).Create(ctx, &row); e != nil {
		return e
	}
	if result.RowsAffected != 0 {
		return nil
	}
	old, e := gorm.G[Entry](db).Where("user_id=? AND id=?", row.UserID, row.ID).First(ctx)
	if e != nil {
		return e
	}
	if old.RequestHash != row.RequestHash {
		return ErrConflict
	}
	return nil
}

type Cursor struct {
	Time time.Time `json:"time"`
	ID   string    `json:"id"`
	Kind string    `json:"kind"`
}

func EncodeCursor(row Entry, kind string) string {
	b, _ := json.Marshal(Cursor{row.OccurredAt, row.ID, kind})
	return base64.RawURLEncoding.EncodeToString(b)
}
func DecodeCursor(raw, kind string) (Cursor, error) {
	var c Cursor
	b, e := base64.RawURLEncoding.DecodeString(raw)
	if e != nil || len(b) > 256 {
		return c, errors.New("游标无效")
	}
	if e = json.Unmarshal(b, &c); e != nil {
		return c, e
	}
	_, e = uuid.Parse(c.ID)
	if e != nil || c.Time.IsZero() || c.Kind != kind {
		return c, errors.New("游标无效")
	}
	return c, nil
}
