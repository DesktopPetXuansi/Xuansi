package platform

import (
	"encoding/json"
	"time"
)

// 数据模型使用显式 JSON 名称；密码、存储键和令牌摘要不暴露给 API。
type User struct {
	ID            string    `json:"id"`
	Email         string    `json:"email"`
	PasswordHash  string    `json:"-"`
	DisplayName   string    `json:"displayName"`
	Role          string    `json:"role"`
	Status        string    `json:"status"`
	EmailVerified bool      `json:"emailVerified"`
	QuotaBytes    int64     `json:"-"`
	UsedBytes     int64     `json:"-"`
	ReservedBytes int64     `json:"-"`
	CreatedAt     time.Time `json:"createdAt"`
	UpdatedAt     time.Time `json:"updatedAt"`
}

func (u User) View() UserView {
	return UserView{u.ID, u.Email, u.DisplayName, u.Role, u.Status, u.EmailVerified, StorageUsage{u.QuotaBytes, u.UsedBytes, u.ReservedBytes}}
}

type StorageUsage struct {
	QuotaBytes    int64 `json:"quotaBytes"`
	UsedBytes     int64 `json:"usedBytes"`
	ReservedBytes int64 `json:"reservedBytes"`
}
type UserView struct {
	ID            string       `json:"id"`
	Email         string       `json:"email"`
	DisplayName   string       `json:"displayName"`
	Role          string       `json:"role"`
	Status        string       `json:"status"`
	EmailVerified bool         `json:"emailVerified"`
	Storage       StorageUsage `json:"storage"`
}
type WebSession struct {
	ID         string    `json:"id"`
	UserID     string    `json:"-"`
	TokenHash  string    `json:"-"`
	CreatedAt  time.Time `json:"createdAt"`
	LastSeenAt time.Time `json:"lastSeenAt"`
	ExpiresAt  time.Time `json:"expiresAt"`
	IsCurrent  bool      `json:"isCurrent" gorm:"-"`
}
type AccountToken struct {
	ID, UserID, Purpose, TokenHash string
	ExpiresAt                      time.Time
	ConsumedAt                     *time.Time
}
type Resource struct {
	ID               string          `json:"id"`
	OwnerID          string          `json:"ownerId"`
	Kind             string          `json:"kind"`
	Name             string          `json:"name"`
	Description      string          `json:"description"`
	Author           string          `json:"author"`
	License          string          `json:"license"`
	Source           string          `json:"source"`
	Tags             json.RawMessage `json:"tags" gorm:"type:jsonb"`
	Visibility       string          `json:"visibility"`
	Status           string          `json:"status"`
	CurrentVersionID *string         `json:"currentVersionId"`
	CoverKey         *string         `json:"-"`
	CoverBytes       int64           `json:"-"`
	CoverURL         *string         `json:"coverUrl" gorm:"-"`
	CreatedAt        time.Time       `json:"createdAt"`
	UpdatedAt        time.Time       `json:"updatedAt"`
}
type ResourceVersion struct {
	ID                   string              `json:"id"`
	ResourceID           string              `json:"resourceId"`
	Version              string              `json:"version"`
	Entrypoint           string              `json:"entrypoint"`
	ValidationStatus     string              `json:"validationStatus"`
	CompatibilityStatus  string              `json:"compatibilityStatus"`
	MinimumClientVersion string              `json:"minimumClientVersion"`
	PackageKey           string              `json:"-"`
	PackageBytes         int64               `json:"packageBytes"`
	PackageSHA256        string              `json:"packageSha256"`
	ValidationReport     json.RawMessage     `json:"validationReport" gorm:"type:jsonb"`
	Manifest             json.RawMessage     `json:"-" gorm:"type:jsonb"`
	CreatedAt            time.Time           `json:"createdAt"`
	Dependencies         []VersionDependency `json:"dependencies" gorm:"-"`
}
type VersionDependency struct {
	VersionID string `json:"versionId"`
	Relation  string `json:"relation"`
}
type ResourceDependency struct{ VersionID, TargetVersionID, Relation string }
type ResourceFile struct {
	VersionID, Path string
	Bytes           int64
	SHA256          string
}
type UserLibrary struct {
	UserID, ResourceID string
	PinnedVersionID    *string
	CreatedAt          time.Time
}

func (UserLibrary) TableName() string { return "user_library" }

type Upload struct {
	ID            string            `json:"id"`
	UserID        string            `json:"-"`
	ResourceID    string            `json:"-"`
	VersionID     *string           `json:"versionId"`
	Purpose       string            `json:"purpose"`
	Filename      string            `json:"-"`
	ExpectedBytes int64             `json:"-"`
	ReservedBytes int64             `json:"-"`
	ObjectKey     string            `json:"-"`
	Status        string            `json:"status"`
	ErrorCode     *string           `json:"errorCode"`
	CreatedAt     time.Time         `json:"createdAt"`
	ExpiresAt     time.Time         `json:"expiresAt"`
	Settled       bool              `json:"-"`
	Method        string            `json:"method" gorm:"-"`
	URL           string            `json:"url" gorm:"-"`
	Headers       map[string]string `json:"headers" gorm:"-"`
}
type Job struct {
	ID         string          `json:"id"`
	Kind       string          `json:"kind"`
	Payload    json.RawMessage `json:"-" gorm:"type:jsonb"`
	Status     string          `json:"status"`
	Attempts   int             `json:"attempts"`
	RunAt      time.Time       `json:"runAt"`
	LeaseUntil *time.Time      `json:"leaseUntil"`
	LeaseOwner *string         `json:"-"`
	LastError  *string         `json:"lastError"`
	CreatedAt  time.Time       `json:"createdAt"`
	DedupeKey  *string         `json:"-"`
}
type DownloadTicket struct {
	ID                    string
	UserID                *string
	ResourceID, VersionID string
	GrantID               *string
	TokenHash             string
	ExpiresAt             time.Time
}
type ClientRelease struct {
	ID           string            `json:"id"`
	Version      string            `json:"version"`
	Channel      string            `json:"channel"`
	SourceCommit string            `json:"sourceCommit"`
	ReleaseNotes string            `json:"releaseNotes"`
	PublishedAt  *time.Time        `json:"publishedAt"`
	CreatedAt    time.Time         `json:"createdAt"`
	Artifacts    []ReleaseArtifact `json:"artifacts" gorm:"foreignKey:ReleaseID"`
}
type ReleaseArtifact struct {
	ID                 string          `json:"id"`
	ReleaseID          string          `json:"-"`
	OS                 string          `json:"os"`
	Arch               string          `json:"arch"`
	DistributionType   string          `json:"distributionType"`
	DownloadURL        string          `json:"downloadUrl"`
	SHA256             string          `json:"sha256"`
	Bytes              int64           `json:"bytes"`
	SystemRequirements json.RawMessage `json:"systemRequirements" gorm:"type:jsonb"`
}
type AuditLog struct {
	ID        string          `json:"id"`
	ActorID   *string         `json:"actorId"`
	Action    string          `json:"action"`
	TargetID  string          `json:"targetId"`
	Details   json.RawMessage `json:"details" gorm:"type:jsonb"`
	CreatedAt time.Time       `json:"createdAt"`
}
type OAuthGrant struct {
	ID          string     `json:"id"`
	UserID      string     `json:"-"`
	DeviceLabel string     `json:"deviceLabel"`
	CreatedAt   time.Time  `json:"createdAt"`
	LastSeenAt  time.Time  `json:"lastSeenAt"`
	RevokedAt   *time.Time `json:"-"`
}
type OAuthRecord struct {
	Signature string
	Kind      string
	RequestID string
	GrantID   string
	Payload   json.RawMessage `gorm:"type:jsonb"`
	Active    bool
	CreatedAt time.Time
}

// OAuth 缩写显式映射，避免GORM自动拆词为 o_auth。
func (OAuthGrant) TableName() string  { return "oauth_grants" }
func (OAuthRecord) TableName() string { return "oauth_records" }
