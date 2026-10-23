package api

import (
	"bytes"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"
)

// 从真实匿名接口验证：公开编号不可携带服务器标识或回显调用者输入。
func TestRequestIDPrivacy(t *testing.T) {
	for _, tc := range []struct {
		name, supplied string
	}{
		{"server_generated", ""},
		{"private_input", "private-person@example.invalid/internal-machine"},
		{"oversized_input", strings.Repeat("private-marker-", 1024)},
		{"caller_uuid", "a5c756b1-949a-4aa2-ae01-06635fe91262"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var logs bytes.Buffer
			s := &Server{Log: slog.New(slog.NewJSONHandler(&logs, nil))}
			router := s.Router()
			seen := map[string]bool{}
			for range 2 {
				logs.Reset()
				r := httptest.NewRequest(http.MethodGet, "/api/v1/me", nil)
				if tc.supplied != "" {
					r.Header.Set("X-Request-ID", tc.supplied)
				}
				w := httptest.NewRecorder()
				router.ServeHTTP(w, r)
				if w.Code != http.StatusUnauthorized {
					t.Fatalf("匿名接口状态异常：%d", w.Code)
				}
				var body struct {
					Error struct {
						Code, Message string
					}
					RequestID string `json:"requestId"`
				}
				if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
					t.Fatal("错误响应不是有效 JSON")
				}
				if body.Error.Code != "UNAUTHORIZED" || body.Error.Message != "请登录" {
					t.Fatal("既有错误响应契约被改变")
				}
				id, err := uuid.Parse(body.RequestID)
				if err != nil || len(body.RequestID) != 36 || id.Version() != 4 || id.Variant() != uuid.RFC4122 {
					t.Fatal("公开请求编号必须为随机 UUID v4，不得带服务器标识或外部输入")
				}
				if body.RequestID == tc.supplied || seen[body.RequestID] {
					t.Fatal("请求编号必须由服务端逐请求生成，不得沿用调用者编号")
				}
				seen[body.RequestID] = true
				var entry struct {
					RequestID string `json:"requestId"`
				}
				if err := json.Unmarshal(bytes.TrimSpace(logs.Bytes()), &entry); err != nil || entry.RequestID != body.RequestID {
					t.Fatal("服务端日志与公开响应的请求编号不一致")
				}
			}
		})
	}
}
