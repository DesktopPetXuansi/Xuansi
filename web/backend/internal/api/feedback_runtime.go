package api

import (
	"net/http"
	"strings"
)

// FeedbackRouter 在身份、数据库与存储处理之前隔离完整平台的其他业务路由。
// 健康探针供内网使用；公网代理只转发 CSRF 和反馈提交。
func (s *Server) FeedbackRouter() http.Handler {
	full := s.Router()
	return s.headers(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/v1/feedback/"), "/")
		management := strings.HasPrefix(r.URL.Path, "/api/v1/feedback/") && len(parts) == 2 && canonicalFeedbackID(parts[0]) && (parts[1] == "management" || parts[1] == "withdrawal")
		allowed := r.Method == http.MethodGet && (r.URL.Path == "/healthz" || r.URL.Path == "/readyz" || r.URL.Path == "/api/v1/auth/csrf") ||
			r.Method == http.MethodPost && (r.URL.Path == "/api/v1/feedback" || management)
		if !allowed {
			http.NotFound(w, r)
			return
		}
		full.ServeHTTP(w, r)
	}))
}
