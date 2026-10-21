package platform

import (
	"strings"
	"testing"
)

// GitHub 授权只属于服务器，仓库、令牌和公开开关必须完整且明确。
func TestFeedbackGitHubConfiguration(t *testing.T) {
	for _, tc := range []struct {
		name, repository, token, public string
		valid                           bool
	}{
		{"未配置时保持原有私有收件", "", "", "", true},
		{"私有仓库", "owner/feedback", "synthetic-token", "false", true},
		{"显式公开仓库", "DesktopPetXuansi/Xuansi", "synthetic-token", "true", true},
		{"缺少令牌", "owner/feedback", "", "", false},
		{"缺少仓库", "", "synthetic-token", "", false},
		{"公开配置不完整", "", "", "true", false},
		{"非法公开开关", "owner/feedback", "synthetic-token", "maybe", false},
		{"拒绝仓库路径注入", "owner/../feedback", "synthetic-token", "true", false},
		{"拒绝凭据换行", "owner/feedback", "synthetic\r\ntoken", "true", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("DATABASE_URL", "postgres://synthetic/xuansi_test")
			t.Setenv("APP_ENV", "development")
			t.Setenv("APP_URL", "http://localhost:3000")
			t.Setenv("STORAGE_DRIVER", "local")
			t.Setenv("FEEDBACK_GITHUB_REPOSITORY", tc.repository)
			t.Setenv("FEEDBACK_GITHUB_TOKEN", tc.token)
			t.Setenv("FEEDBACK_GITHUB_PUBLIC", tc.public)
			c, err := LoadConfig()
			if (err == nil) != tc.valid {
				t.Fatalf("配置校验结果错误: %v", err)
			}
			if err != nil && tc.token != "" && strings.Contains(err.Error(), tc.token) {
				t.Fatal("配置错误暴露了令牌")
			}
			if tc.valid && (c.FeedbackGitHubRepository != tc.repository || c.FeedbackGitHubPublic != (tc.public == "true")) {
				t.Fatal("GitHub 收件配置未正确加载")
			}
		})
	}
}
