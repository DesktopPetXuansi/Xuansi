package platform

import (
	"strings"
	"testing"
)

// 暂停邮件只豁免 SMTP，不得连带放宽其他生产安全要求。
func TestMailDeliveryDisabledConfig(t *testing.T) {
	for _, tc := range []struct {
		name, flag, smtp, origin, secret, storage string
		valid, disabled                           bool
	}{
		{"默认开启", "", "smtp.example.invalid", "https://site.example.invalid", strings.Repeat("x", 32), "s3", true, false},
		{"显式开启", "false", "smtp.example.invalid", "https://site.example.invalid", strings.Repeat("x", 32), "s3", true, false},
		{"暂停无需SMTP", "true", "localhost", "https://site.example.invalid", strings.Repeat("x", 32), "s3", true, true},
		{"非法布尔值", "paused", "smtp.example.invalid", "https://site.example.invalid", strings.Repeat("x", 32), "s3", false, false},
		{"启用仍需SMTP", "false", "localhost", "https://site.example.invalid", strings.Repeat("x", 32), "s3", false, false},
		{"暂停仍需HTTPS", "true", "localhost", "http://site.example.invalid", strings.Repeat("x", 32), "s3", false, true},
		{"暂停仍需OAuth", "true", "localhost", "https://site.example.invalid", "", "s3", false, true},
		{"暂停仍需S3", "true", "localhost", "https://site.example.invalid", strings.Repeat("x", 32), "local", false, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			for key, value := range map[string]string{
				"APP_ENV": "production", "APP_URL": tc.origin, "DATABASE_URL": "unused", "STORAGE_DRIVER": tc.storage,
				"SMTP_HOST": tc.smtp, "OAUTH_SECRET": tc.secret, "MAIL_DELIVERY_DISABLED": tc.flag,
				"S3_ENDPOINT": "http://127.0.0.1:19000", "S3_PUBLIC_ENDPOINT": "", "S3_BUCKET": "test",
				"S3_ACCESS_KEY_ID": "fixture-key", "S3_SECRET_ACCESS_KEY": "fixture-secret",
				"FEEDBACK_GITHUB_REPOSITORY": "", "FEEDBACK_GITHUB_TOKEN": "", "FEEDBACK_GITHUB_PUBLIC": "false", "TRUSTED_PROXY_CIDRS": "",
			} {
				t.Setenv(key, value)
			}
			config, err := LoadConfig()
			if (err == nil) != tc.valid {
				t.Fatal("邮件暂停配置有效性不正确")
			}
			if tc.valid && config.MailDeliveryDisabled != tc.disabled {
				t.Fatal("邮件暂停开关未按配置生效")
			}
		})
	}
}
