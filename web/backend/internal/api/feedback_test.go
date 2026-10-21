package api

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"xuansi/web/backend/internal/platform"
)

// 无数据库也能证明端点存在且校验匿名提交的请求编号。
func TestFeedbackEndpointRejectsInvalidID(t *testing.T) {
	s := &Server{Config: platform.Config{AppURL: "http://localhost:3000"}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/feedback", strings.NewReader(`{"category":"BUG","title":"问题","description":"说明"}`))
	r.Header.Set("Origin", s.Config.AppURL)
	r.Header.Set("X-CSRF-Token", "test")
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: "test"})
	w := httptest.NewRecorder()
	s.Router().ServeHTTP(w, r)
	if w.Code != 400 {
		t.Fatalf("应校验请求编号，实际%d: %s", w.Code, w.Body.String())
	}
}

// 无DB输入检查防止正文、自由诊断及尾随JSON进入存储层。
func TestFeedbackStrictInput(t *testing.T) {
	cases := []struct {
		name, body, key string
		status          int
	}{
		{"空标题", `{"category":"BUG","title":"  ","description":"内容"}`, "", 400},
		{"长标题", `{"category":"BUG","title":"` + strings.Repeat("中", 81) + `","description":"内容"}`, "", 400},
		{"长正文", `{"category":"BUG","title":"问题","description":"` + strings.Repeat("字", 4001) + `"}`, "", 400},
		{"长联系方式", `{"category":"BUG","title":"问题","description":"内容","contact":"` + strings.Repeat("字", 161) + `"}`, "", 400},
		{"未知字段", `{"category":"BUG","title":"问题","description":"内容","token":"秘密"}`, "", 400},
		{"未知诊断", `{"category":"BUG","title":"问题","description":"内容","diagnostics":{"path":"秘密"}}`, "", 400},
		{"长诊断", `{"category":"BUG","title":"问题","description":"内容","diagnostics":{"system":"` + strings.Repeat("字", 81) + `"}}`, "", 400},
		{"尾随", `{"category":"BUG","title":"问题","description":"内容"} {}`, "", 400},
		{"32KiB", `{"category":"BUG","title":"问题","description":"` + strings.Repeat("a", 33000) + `"}`, "", 413},
		{"零UUID", `{}`, "00000000-0000-0000-0000-000000000000", 400},
		{"非规范UUID", `{}`, "A0000000-0000-4000-8000-000000000001", 400},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s := &Server{Config: platform.Config{AppURL: "http://localhost:3000"}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
			r := httptest.NewRequest("POST", "/api/v1/feedback", strings.NewReader(tc.body))
			r.Header.Set("Origin", s.Config.AppURL)
			r.Header.Set("X-CSRF-Token", "test")
			r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: "test"})
			key := tc.key
			if key == "" {
				key = "10000000-0000-4000-8000-000000000001"
			}
			r.Header.Set("Idempotency-Key", key)
			w := httptest.NewRecorder()
			s.Router().ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("%d: %s", w.Code, w.Body.String())
			}
		})
	}
}
func TestFeedbackCSRFAndPrivateRoutes(t *testing.T) {
	s := &Server{Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	for _, tc := range []struct {
		method, path string
		status       int
	}{{"POST", "/api/v1/feedback", 403}, {"GET", "/api/v1/admin/feedback", 401}, {"PATCH", "/api/v1/admin/feedback/10000000-0000-4000-8000-000000000001", 403}} {
		w := httptest.NewRecorder()
		s.Router().ServeHTTP(w, httptest.NewRequest(tc.method, tc.path, strings.NewReader(`{}`)))
		if w.Code != tc.status {
			t.Fatalf("%s %s: %d", tc.method, tc.path, w.Code)
		}
	}
	for _, method := range []string{"POST", "GET", "PATCH"} {
		for _, path := range []string{"/api/v1/feedback", "/api/v1/admin/feedback", "/api/v1/admin/feedback/10000000-0000-4000-8000-000000000001"} {
			if bearerAllowed(method, path, []string{"resources:read", "resources:write", "history:read", "history:write"}) {
				t.Fatal("反馈获得资源Bearer权限")
			}
		}
	}
}
func TestFeedbackRateLimitSeparateFromAuth(t *testing.T) {
	s := &Server{}
	h := s.rateLimit(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
	call := func(path string) int {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", path, nil))
		return w.Code
	}
	for i := 0; i < 5; i++ {
		if call("/api/v1/feedback") != 204 {
			t.Fatal("过早限流")
		}
	}
	if call("/api/v1/feedback") != 429 {
		t.Fatal("反馈未限流")
	}
	for i := 0; i < 20; i++ {
		if call("/api/v1/auth/login") != 204 {
			t.Fatal("认证额度受影响")
		}
	}
	if call("/api/v1/auth/login") != 429 {
		t.Fatal("认证未限流")
	}
}
