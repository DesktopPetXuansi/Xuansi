package api

import (
	"github.com/google/uuid"
	"strings"
	"testing"
)

// 认领只转移未来会话权限，匿名历史不能借旧请求编号冒充账号发言。
func TestPostgresAccountClaimPreservesAnonymousHistoryAndActorReceipt(t *testing.T) {
	s, a := setupModeration(t)
	id := uuid.NewString()
	input := moderationInput("匿名历史合成问题", false)
	feedbackCall(t, a, id, input, 201)
	key := uuid.NewString()
	token := strings.Repeat("a", 64)
	old := map[string]string{"body": "认领前匿名发言", "managementToken": token}
	messageCall(t, a, "POST", "/api/v1/feedback/"+id+"/messages", key, old, 201)
	registered(t, s, a, "claim-history@example.test")
	path := "/api/v1/me/feedback/" + id
	a.call("POST", path+"/claim", map[string]string{"managementToken": token}, 200, "")
	messageCall(t, a, "POST", path+"/messages", key, map[string]string{"body": "认领前匿名发言"}, 409)
	view := data[feedbackConversation](t, a.call("GET", path+"/messages", nil, 200, ""))
	if view.SubmitterName != "" || len(view.Messages) != 1 || view.Messages[0].AuthorName != "" {
		t.Fatal("匿名历史被回填账号昵称")
	}
	messageCall(t, a, "POST", path+"/messages", uuid.NewString(), map[string]string{"body": "认领后账号发言"}, 201)
	for _, state := range []string{"SPAM", "WITHDRAWN", "WITHDRAWAL_REQUESTED"} {
		if e := s.DB.Model(&feedbackEntry{}).Where("id=?", id).Update("moderation_status", state).Error; e != nil {
			t.Fatal(e)
		}
		a.call("POST", path+"/claim", map[string]string{"managementToken": token}, 409, "")
		messageCall(t, a, "POST", path+"/messages", uuid.NewString(), map[string]string{"body": "关闭后消息"}, 409)
	}
}

// 关闭状态不能先于原凭据校验返回，避免用错误凭据推断匿名记录是否存在。
func TestPostgresAccountClaimRejectsWrongTokenBeforeState(t *testing.T) {
	s, a := setupModeration(t)
	registered(t, s, a, "claim-state@example.test")
	id := uuid.NewString()
	feedbackCall(t, a, id, moderationInput("旧匿名关闭状态权限测试", false), 201)
	path := "/api/v1/me/feedback/" + id + "/claim"
	for _, state := range []string{"SPAM", "WITHDRAWN", "WITHDRAWAL_REQUESTED"} {
		if e := s.DB.Model(&feedbackEntry{}).Where("id=?", id).Update("moderation_status", state).Error; e != nil {
			t.Fatal(e)
		}
		a.call("POST", path, map[string]string{"managementToken": strings.Repeat("b", 64)}, 404, "")
		a.call("POST", path, map[string]string{"managementToken": strings.Repeat("a", 64)}, 409, "")
	}
}
