package platform

import (
	"fmt"
	"strings"
	"time"

	"xuansi/web/backend/internal/feedbackgithub"
)

// 反馈由 API 和后台任务共享；投递信息不进入匿名收据或现有网页契约。
type FeedbackDiagnostics struct {
	AppVersion    string `json:"appVersion,omitempty"`
	System        string `json:"system,omitempty"`
	Architecture  string `json:"architecture,omitempty"`
	PythonVersion string `json:"pythonVersion,omitempty"`
	QtVersion     string `json:"qtVersion,omitempty"`
}

type FeedbackEntry struct {
	ID                string               `json:"id"`
	IdempotencyKey    string               `json:"-"`
	RequestHash       string               `json:"-"`
	Category          string               `json:"category"`
	Title             string               `json:"title"`
	Description       string               `json:"description"`
	Contact           string               `json:"contact"`
	Diagnostics       *FeedbackDiagnostics `json:"diagnostics" gorm:"serializer:json"`
	Status            string               `json:"status"`
	CreatedAt         time.Time            `json:"createdAt"`
	UpdatedAt         time.Time            `json:"updatedAt"`
	PublicConsent     bool                 `json:"-"`
	GitHubRepository  string               `json:"-"`
	GitHubPublic      bool                 `json:"-"`
	GitHubIssueNumber int64                `json:"-"`
	GitHubIssueURL    string               `json:"-"`
}

func (FeedbackEntry) TableName() string { return "feedback" }

// 未配置时保留私有收件；部分配置错误直接阻止启动，错误绝不包含令牌。
func validateFeedbackGitHub(c Config) error {
	if c.FeedbackGitHubRepository == "" && c.FeedbackGitHubToken == "" && !c.FeedbackGitHubPublic {
		return nil
	}
	if c.FeedbackGitHubRepository == "" || c.FeedbackGitHubToken == "" || strings.ContainsAny(c.FeedbackGitHubToken, "\r\n\t ") {
		return fmt.Errorf("必须完整配置 FEEDBACK_GITHUB_REPOSITORY 与 FEEDBACK_GITHUB_TOKEN")
	}
	if _, err := feedbackgithub.New(c.FeedbackGitHubRepository, c.FeedbackGitHubToken, c.FeedbackGitHubPublic, nil); err != nil {
		return fmt.Errorf("GitHub 反馈仓库或授权配置无效")
	}
	return nil
}
