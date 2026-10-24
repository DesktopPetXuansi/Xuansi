package api

import (
	"bytes"
	"encoding/json"
	"github.com/google/uuid"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// 只在隔离库发送合成请求，覆盖真实会话与 CSRF 保护。
func messageCall(t *testing.T, c *testClient, method, path, key string, input interface{}, expected int) []byte {
	t.Helper()
	body, _ := json.Marshal(input)
	r := httptest.NewRequest(method, path, bytes.NewReader(body))
	r.RemoteAddr = "198.51.100.42:8080"
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", c.csrf)
	r.Header.Set("Idempotency-Key", key)
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	if c.session != "" {
		r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: c.session})
	}
	w := httptest.NewRecorder()
	c.handler.ServeHTTP(w, r)
	if w.Code != expected {
		t.Fatalf("对话 %s: %d != %d: %s", method, w.Code, expected, w.Body.String())
	}
	return w.Body.Bytes()
}
func TestPostgresFeedbackConversationRoundtrip(t *testing.T) {
	s, c := setupModeration(t)
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("私有对话合成问题", false), 201)
	path := "/api/v1/feedback/" + id + "/messages"
	token := strings.Repeat("a", 64)
	c.call("GET", "/api/v1/admin/feedback/"+id+"/messages", nil, 401, "")
	c.call("POST", path+"/query", map[string]string{"managementToken": token}, 200, "")
	messageCall(t, c, "POST", path, uuid.NewString(), map[string]string{"managementToken": strings.Repeat("b", 64), "body": "越权"}, 403)
	moderationAdmin(t, s, c)
	adminPath := "/api/v1/admin/feedback/" + id + "/messages"
	key := uuid.NewString()
	input := map[string]interface{}{"body": "开发者合成回复", "resolve": true}
	first := messageCall(t, c, "POST", adminPath, key, input, 201)
	replay := messageCall(t, c, "POST", adminPath, key, input, 200)
	if !bytes.Equal(first, replay) {
		t.Fatal("幂等收据改变")
	}
	messageCall(t, c, "POST", adminPath, key, map[string]interface{}{"body": "不同正文", "resolve": true}, 409)
	messageCall(t, c, "POST", path, uuid.NewString(), map[string]string{"managementToken": token, "body": "用户合成补充"}, 201)
	var view struct {
		Data struct {
			Status   string
			CanReply bool
			Messages []struct{ Body, AuthorRole string }
		}
	}
	raw := c.call("POST", path+"/query", map[string]string{"managementToken": token}, 200, "")
	if e := json.Unmarshal(raw, &view); e != nil {
		t.Fatal(e)
	}
	if view.Data.Status != "NEW" || !view.Data.CanReply || len(view.Data.Messages) != 2 {
		t.Fatalf("对话/重开失败: %s", raw)
	}
	for _, secret := range []string{"example.test", "managementToken", "actorId", "userId"} {
		if bytes.Contains(raw, []byte(secret)) {
			t.Fatalf("私有身份泄漏: %s", secret)
		}
	}
	moderationJobCount(t, s, 0)
	c.call("POST", "/api/v1/feedback/"+id+"/withdrawal", map[string]string{"managementToken": token}, 200, "")
	raw = c.call("POST", path+"/query", map[string]string{"managementToken": token}, 200, "")
	if bytes.Contains(raw, []byte("合成回复")) || bytes.Contains(raw, []byte("合成补充")) {
		t.Fatal("撤回仍返回私信")
	}
	messageCall(t, c, "POST", adminPath, key, input, 409)
}
