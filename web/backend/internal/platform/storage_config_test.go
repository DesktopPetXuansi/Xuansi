package platform

import (
	"strings"
	"testing"
)

// 公网上传地址不接受凭据、路径、查询或生产明文来源，空值保持单端点兼容。
func TestS3PublicEndpointConfig(t *testing.T) {
	for _, test := range []struct {
		name, endpoint string
		valid          bool
	}{
		{"默认复用后台端点", "", true},
		{"公网HTTPS", "https://uploads.example.invalid/", true},
		{"拒绝生产HTTP", "http://uploads.example.invalid", false},
		{"拒绝凭据", "https://user:secret@uploads.example.invalid", false},
		{"拒绝路径", "https://uploads.example.invalid/storage", false},
		{"拒绝查询", "https://uploads.example.invalid?token=secret", false},
		{"拒绝片段", "https://uploads.example.invalid#fragment", false},
		{"拒绝相对来源", "/storage", false},
	} {
		t.Run(test.name, func(t *testing.T) {
			for key, value := range map[string]string{
				"APP_ENV": "production", "APP_URL": "https://site.example.invalid", "DATABASE_URL": "unused",
				"STORAGE_DRIVER": "s3", "S3_ENDPOINT": "http://127.0.0.1:19000", "S3_PUBLIC_ENDPOINT": test.endpoint,
				"S3_BUCKET": "test", "S3_ACCESS_KEY_ID": "fixture-key", "S3_SECRET_ACCESS_KEY": "fixture-secret",
				"SMTP_HOST": "smtp.example.invalid", "OAUTH_SECRET": strings.Repeat("x", 32),
				"FEEDBACK_GITHUB_REPOSITORY": "", "FEEDBACK_GITHUB_TOKEN": "", "FEEDBACK_GITHUB_PUBLIC": "false",
			} {
				t.Setenv(key, value)
			}
			config, err := LoadConfig()
			if (err == nil) != test.valid {
				t.Fatalf("公网存储配置有效性错误: %v", err)
			}
			if test.valid && strings.HasSuffix(config.S3PublicEndpoint, "/") {
				t.Fatal("公网来源尾斜线未规范化")
			}
		})
	}
}
