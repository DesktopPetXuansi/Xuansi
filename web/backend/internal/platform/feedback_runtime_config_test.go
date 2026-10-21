package platform

import (
	"strings"
	"testing"
)

// 反馈部署无需伪造资源平台的存储、邮件或 OAuth 凭据。
func TestFeedbackRuntimeConfiguration(t *testing.T) {
	for _, tc := range []struct {
		name, environment, origin, proxies, repository, token, public string
		valid                                                         bool
	}{
		{"生产独立收件", "production", "https://xuansi.kukude.top", "172.17.0.0/16", "", "", "", true},
		{"生产公开投递", "production", "https://xuansi.kukude.top/", "172.17.0.2/32", "DesktopPetXuansi/Xuansi", "synthetic-token", "true", true},
		{"开发回环", "development", "http://127.0.0.1:8189", "", "", "", "", true},
		{"生产拒绝HTTP", "production", "http://xuansi.kukude.top", "", "", "", "", false},
		{"开发拒绝公网HTTP", "development", "http://xuansi.kukude.top", "", "", "", "", false},
		{"拒绝路径", "production", "https://xuansi.kukude.top/private", "", "", "", "", false},
		{"拒绝用户信息", "production", "https://user:secret@xuansi.kukude.top", "", "", "", "", false},
		{"拒绝全部代理", "production", "https://xuansi.kukude.top", "0.0.0.0/0", "", "", "", false},
		{"拒绝错误代理", "production", "https://xuansi.kukude.top", "invalid", "", "", "", false},
		{"缺少专用令牌", "production", "https://xuansi.kukude.top", "", "DesktopPetXuansi/Xuansi", "", "true", false},
		{"拒绝错误开关", "production", "https://xuansi.kukude.top", "", "DesktopPetXuansi/Xuansi", "synthetic-token", "yes", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for key, value := range map[string]string{
				"DATABASE_URL": "postgres://synthetic/xuansi_test", "APP_ENV": tc.environment,
				"APP_URL": tc.origin, "TRUSTED_PROXY_CIDRS": tc.proxies,
				"FEEDBACK_GITHUB_REPOSITORY": tc.repository, "FEEDBACK_GITHUB_TOKEN": tc.token,
				"FEEDBACK_GITHUB_PUBLIC": tc.public, "SMTP_HOST": "", "OAUTH_SECRET": "",
				"S3_SECRET_ACCESS_KEY": "", "HTTP_ADDRESS": "127.0.0.1:8189",
			} {
				t.Setenv(key, value)
			}
			c, err := LoadFeedbackConfig()
			if (err == nil) != tc.valid {
				t.Fatalf("配置有效性错误: %v", err)
			}
			if err != nil && tc.token != "" && strings.Contains(err.Error(), tc.token) {
				t.Fatal("配置错误泄露令牌")
			}
			if tc.valid && c.AppURL != strings.TrimRight(tc.origin, "/") {
				t.Fatal("Origin 未归一化")
			}
		})
	}
}

func TestFeedbackRuntimeRequiresDatabase(t *testing.T) {
	t.Setenv("DATABASE_URL", "")
	t.Setenv("APP_URL", "https://xuansi.kukude.top")
	if _, err := LoadFeedbackConfig(); err == nil {
		t.Fatal("缺失数据库应拒绝启动")
	}
}
