package api

import "net/http"

// 在解析表单和写库前拒绝发信，避免留下无法交付的账号、令牌或任务。
func (s *Server) mailDeliveryPaused(w http.ResponseWriter, r *http.Request) bool {
	if !s.Config.MailDeliveryDisabled {
		return false
	}
	problem(w, r, http.StatusServiceUnavailable, "MAIL_DELIVERY_PAUSED", "邮件服务暂时停用，注册、邮箱验证和密码重置暂不可用。已有账号仍可登录，下载和基础使用不受影响。")
	return true
}
