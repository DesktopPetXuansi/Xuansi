package api

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"xuansi/web/backend/internal/platform"
)

// 使用空数据库和无效输入，证明暂停在解析、建号和创建令牌之前返回。
func TestAuthMailDeliveryPaused(t *testing.T) {
	s := &Server{Config: platform.Config{MailDeliveryDisabled: true}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	for _, tc := range []struct {
		name    string
		handler http.HandlerFunc
	}{
		{"旧注册", s.register}, {"注册验证码", s.requestRegistrationCode},
		{"验证邮箱", s.requestToken("VERIFY")}, {"重置密码", s.requestToken("RESET")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			tc.handler(w, httptest.NewRequest(http.MethodPost, "/", strings.NewReader("invalid-json")))
			var body struct {
				Error struct{ Code, Message string }
			}
			if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil || w.Code != http.StatusServiceUnavailable || body.Error.Code != "MAIL_DELIVERY_PAUSED" || !strings.Contains(body.Error.Message, "邮件服务暂时停用") {
				t.Fatal("暂停状态未返回可读的 503 邮件暂停提示")
			}
		})
	}
}

// 带有效 CSRF 和真实数据库走公开路由，暂停操作不得留下账号或待发任务。
func TestPostgresAuthMailPauseDoesNotCreateRecords(t *testing.T) {
	s, client, _ := setup(t)
	s.Config.MailDeliveryDisabled = true
	input := map[string]string{"email": "pause-test@example.invalid", "password": "test-strong-password-123", "displayName": "测试用户"}
	for _, path := range []string{"/api/v1/auth/register", "/api/v1/auth/registration-codes", "/api/v1/auth/email-verifications", "/api/v1/auth/password-resets"} {
		body := client.call(http.MethodPost, path, input, http.StatusServiceUnavailable, "")
		var response struct{ Error struct{ Code string } }
		if err := json.Unmarshal(body, &response); err != nil || response.Error.Code != "MAIL_DELIVERY_PAUSED" {
			t.Fatal("路由未保留邮件暂停错误")
		}
	}
	for _, table := range []string{"users", "account_tokens", "registration_challenges", "registration_send_limits", "jobs"} {
		var count int64
		if err := s.DB.Table(table).Count(&count).Error; err != nil || count != 0 {
			t.Fatal("邮件暂停操作创建了不应存在的记录")
		}
	}
}
