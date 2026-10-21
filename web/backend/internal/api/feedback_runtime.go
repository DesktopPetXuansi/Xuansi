package api

import "net/http"

// FeedbackRouter 在身份、数据库与存储处理之前隔离完整平台的其他业务路由。
// 健康探针供内网使用；公网代理只转发 CSRF 和反馈提交。
func (s *Server) FeedbackRouter() http.Handler {
	full := s.Router()
	return s.headers(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		allowed := r.Method == http.MethodGet && (r.URL.Path == "/healthz" || r.URL.Path == "/readyz" || r.URL.Path == "/api/v1/auth/csrf") ||
			r.Method == http.MethodPost && r.URL.Path == "/api/v1/feedback"
		if !allowed {
			http.NotFound(w, r)
			return
		}
		full.ServeHTTP(w, r)
	}))
}
