package api

import (
	"net"
	"net/http"
	"strings"

	"xuansi/web/backend/internal/platform"
)

// 只返回用户完成表单所需的规则，SMTP账号和密钥不进入浏览器。
func (s *Server) authConfig(w http.ResponseWriter, r *http.Request) {
	type password struct {
		MinLength int `json:"minLength"`
		MaxLength int `json:"maxLength"`
	}
	type email struct {
		Mode     string  `json:"mode"`
		InboxURL *string `json:"inboxUrl"`
	}
	mail := email{Mode: "SMTP"}
	host := strings.ToLower(s.Config.SMTPHost)
	ip := net.ParseIP(host)
	// 对应项目本机和Compose的Mailpit配置；生产始终不公开开发收件箱。
	if s.Config.Environment == "development" && s.Config.SMTPPort == "1025" && (host == "localhost" || host == "mail" || ip != nil && ip.IsLoopback()) {
		inbox := "http://127.0.0.1:8025"
		mail = email{Mode: "LOCAL_MAILBOX", InboxURL: &inbox}
	}
	reply(w, 200, struct {
		Password password `json:"password"`
		Email    email    `json:"email"`
	}{password{platform.PasswordMinLength, platform.PasswordMaxLength}, mail})
}
