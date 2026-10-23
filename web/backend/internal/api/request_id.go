package api

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
)

// 每个请求生成独立随机编号，不公开主机名，也不回显外部 X-Request-ID。
// 复用 chi 上下文键，让现有错误响应与服务端日志仍可按同一编号关联。
func privateRequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.WithValue(r.Context(), middleware.RequestIDKey, uuid.NewString())
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
