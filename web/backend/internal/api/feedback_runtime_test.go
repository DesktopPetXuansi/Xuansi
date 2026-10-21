package api

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"xuansi/web/backend/internal/platform"
)

// 没有数据库、存储和 OAuth 时也必须在业务处理前隔离其他平台路由。
func TestFeedbackRuntimeRouteBoundary(t *testing.T) {
	s := &Server{Config: platform.Config{AppURL: "https://xuansi.kukude.top"}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	handler := s.FeedbackRouter()
	for _, tc := range []struct {
		method, path string
		status       int
	}{
		{"GET", "/healthz", 200}, {"GET", "/api/v1/auth/csrf", 200},
		{"POST", "/api/v1/feedback", 403},
		{"POST", "/api/v1/feedback/10000000-0000-4000-8000-000000000001/management", 403},
		{"POST", "/api/v1/feedback/10000000-0000-4000-8000-000000000001/withdrawal", 403},
		{"POST", "/api/v1/feedback/10000000-0000-4000-8000-000000000001/moderation", 404},
		{"POST", "/api/v1/auth/register", 404}, {"GET", "/api/v1/resources", 404},
		{"GET", "/api/v1/admin/feedback", 404}, {"GET", "/oauth/authorize", 404},
		{"GET", "/api/v1/feedback", 404}, {"DELETE", "/api/v1/feedback", 404},
		{"POST", "/api/v1/auth/csrf", 404}, {"GET", "/api/v1/feedback/", 404},
	} {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		if tc.status == 404 {
			r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: "must-not-query-database"})
		}
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		if w.Code != tc.status {
			t.Errorf("%s %s: %d != %d", tc.method, tc.path, w.Code, tc.status)
		}
	}
}
