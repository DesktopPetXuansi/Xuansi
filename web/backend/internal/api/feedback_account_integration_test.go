package api

import (
	"bytes"
	"encoding/json"
	"github.com/google/uuid"
	"strings"
	"testing"
)

// 账号身份来自真实网站会话，合成两账号验证所有权不能经请求正文或请求编号转移。
func TestPostgresAccountFeedbackOwnershipAndClaim(t *testing.T) {
	s, a := setupModeration(t)
	registered(t, s, a, "chat-a@example.test")
	b := &testClient{t: t, handler: s.Router(), csrf: a.csrf}
	registered(t, s, b, "chat-b@example.test")
	key := uuid.NewString()
	input := moderationInput("账号聊天合成问题", false)
	delete(input, "managementToken")
	messageCall(t, a, "POST", "/api/v1/me/feedback", key, input, 201)
	messageCall(t, b, "POST", "/api/v1/me/feedback", key, input, 409)
	feedbackCall(t, b, key, input, 409)
	path := "/api/v1/me/feedback/" + key
	b.call("GET", path+"/messages", nil, 404, "")
	messageCall(t, b, "POST", path+"/messages", uuid.NewString(), map[string]string{"body": "越权"}, 404)
	raw := a.call("GET", path+"/messages", nil, 200, "")
	if !bytes.Contains(raw, []byte(`"kind":"ACCOUNT"`)) || bytes.Contains(raw, []byte("@example.test")) {
		t.Fatalf("身份摘要错误: %s", raw)
	}
	guest := uuid.NewString()
	feedbackCall(t, b, guest, moderationInput("旧匿名认领合成问题", false), 201)
	claim := "/api/v1/me/feedback/" + guest + "/claim"
	token := strings.Repeat("a", 64)
	a.call("POST", claim, map[string]string{"managementToken": token}, 200, "")
	a.call("POST", claim, map[string]string{"managementToken": token}, 200, "")
	b.call("POST", claim, map[string]string{"managementToken": token}, 404, "")
	a.call("POST", "/api/v1/feedback/"+guest+"/management", map[string]string{"managementToken": token}, 403, "")
	raw = a.call("GET", "/api/v1/me/feedback/"+guest+"/messages", nil, 200, "")
	var view struct {
		Data struct{ SubmitterName string }
	}
	if json.Unmarshal(raw, &view) != nil || view.Data.SubmitterName != "" {
		t.Fatal("认领回填了原匿名署名")
	}
}
