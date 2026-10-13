package api

import (
	"strings"
	"testing"
)

// 配置只公开表单规则和本地邮件入口，不能把 SMTP 凭据发送给浏览器。
func TestPostgresAuthConfigPasswordAndEmailMode(t *testing.T) {
	s, c, _ := setup(t)
	type config struct {
		Password struct{ MinLength, MaxLength int }
		Email    struct {
			Mode     string
			InboxURL *string
		}
	}
	assertConfig := func(mode string, inbox bool) {
		t.Helper()
		body := c.call("GET", "/api/v1/auth/config", nil, 200, "")
		view := data[config](t, body)
		if view.Password.MinLength != 12 || view.Password.MaxLength != 128 || view.Email.Mode != mode || (view.Email.InboxURL != nil) != inbox {
			t.Fatalf("表单规则或邮件模式不正确：%+v", view)
		}
		if strings.Contains(string(body), "smtp-secret-only-for-test") {
			t.Fatal("SMTP密码被配置接口公开")
		}
	}
	s.Config.SMTPPassword = "smtp-secret-only-for-test"
	assertConfig("LOCAL_MAILBOX", true)
	s.Config.SMTPHost = "mail"
	assertConfig("LOCAL_MAILBOX", true)
	s.Config.SMTPHost = "smtp.example.invalid"
	s.Config.SMTPPort = "587"
	assertConfig("SMTP", false)
	s.Config.Environment = "production"
	s.Config.SMTPHost = "127.0.0.1"
	s.Config.SMTPPort = "1025"
	assertConfig("SMTP", false)
}
