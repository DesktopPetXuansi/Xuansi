package api

import (
	"bytes"
	"encoding/json"
	"github.com/google/uuid"
	"testing"
)

// 真实数据库确认水位只前进到已显示的消息，迟到确认不会吞后续回复。
func TestPostgresAccountChatNamesReadWatermarkAndWithdrawal(t *testing.T) {
	s, a := setupModeration(t)
	user := registered(t, s, a, "chat-reader@example.test")
	if e := s.DB.Exec("UPDATE users SET display_name='小玄' WHERE id=?", user.ID).Error; e != nil {
		t.Fatal(e)
	}
	admin := &testClient{t: t, handler: s.Router(), csrf: a.csrf}
	moderationAdmin(t, s, admin)
	id := uuid.NewString()
	in := moderationInput("账号读水位问题", false)
	delete(in, "managementToken")
	messageCall(t, a, "POST", "/api/v1/me/feedback", id, in, 201)
	path := "/api/v1/me/feedback/" + id
	ap := "/api/v1/admin/feedback/" + id
	view := data[feedbackConversation](t, a.call("GET", path+"/messages", nil, 200, ""))
	if view.SubmitterName != "小玄" || view.Participant.DisplayName != "小玄" || view.Contact != nil {
		t.Fatal("账号身份或contact边界错误")
	}
	av := data[feedbackConversation](t, admin.call("GET", ap+"/messages", nil, 200, ""))
	if av.UnreadCount != 1 || av.Contact == nil {
		t.Fatal("管理员初始未读错误")
	}
	var before feedbackEntry
	s.DB.Where("id=?", id).First(&before)
	admin.call("POST", ap+"/read", map[string]string{"messageId": id}, 204, "")
	var after feedbackEntry
	s.DB.Where("id=?", id).First(&after)
	if !before.UpdatedAt.Equal(after.UpdatedAt) {
		t.Fatal("标已读改变会话排序时间")
	}
	first := data[messageReceipt](t, messageCall(t, admin, "POST", ap+"/messages", uuid.NewString(), map[string]string{"body": "开发者第一条"}, 201))
	if first.Message.AuthorName != "玄司开发者" {
		t.Fatal("开发者未使用公开昵称")
	}
	a.call("POST", path+"/read", map[string]string{"messageId": first.Message.ID}, 204, "")
	second := data[messageReceipt](t, messageCall(t, admin, "POST", ap+"/messages", uuid.NewString(), map[string]string{"body": "开发者第二条"}, 201))
	// 一个旧读请求晚于新消息到达，仍只确认第一条。
	a.call("POST", path+"/read", map[string]string{"messageId": first.Message.ID}, 204, "")
	a.call("POST", path+"/read", map[string]string{"messageId": id}, 204, "")
	view = data[feedbackConversation](t, a.call("GET", path+"/messages", nil, 200, ""))
	if view.UnreadCount != 1 {
		t.Fatalf("旧水位吞新消息: %d", view.UnreadCount)
	}
	a.call("POST", path+"/read", map[string]string{"messageId": uuid.NewString()}, 404, "")
	a.call("POST", path+"/read", map[string]string{"messageId": second.Message.ID}, 204, "")
	key := uuid.NewString()
	body := map[string]string{"body": "账号补充合成内容"}
	receipt := data[messageReceipt](t, messageCall(t, a, "POST", path+"/messages", key, body, 201))
	if receipt.Message.AuthorName != "小玄" {
		t.Fatal("用户消息未保存当前昵称")
	}
	messageCall(t, admin, "POST", ap+"/messages", uuid.NewString(), map[string]interface{}{"body": "确认解决", "resolve": true}, 201)
	replay := data[messageReceipt](t, messageCall(t, a, "POST", path+"/messages", key, body, 200))
	if replay.FeedbackStatus != "RESOLVED" || replay.Message != receipt.Message {
		t.Fatal("账号幂等未保持原消息和当前状态")
	}
	a.call("POST", path+"/withdrawal", map[string]string{}, 200, "")
	raw := a.call("GET", path+"/messages", nil, 200, "")
	view = data[feedbackConversation](t, raw)
	if view.UnreadCount != 0 || view.Description != "" || view.SubmitterName != "" || len(view.Messages) != 0 {
		t.Fatal("撤回泄漏正文/昵称/未读")
	}
	if bytes.Contains(raw, []byte("小玄")) {
		t.Fatal("撤回后仍暴露昵称")
	}
	var stored struct{ Count int64 }
	s.DB.Raw("SELECT count(*) FROM feedback_messages WHERE feedback_id=? AND (body<>'' OR author_name<>'')", id).Scan(&stored)
	if stored.Count != 0 {
		t.Fatal("撤回未物理清零")
	}
	messageCall(t, a, "POST", path+"/messages", key, body, 409)
	admin.call("POST", ap+"/read", map[string]string{"messageId": second.Message.ID}, 204, "")
	var page struct{ Data []feedbackThread }
	raw = admin.call("GET", "/api/v1/admin/feedback/conversations", nil, 200, "")
	_ = json.Unmarshal(raw, &page)
	if len(page.Data) != 1 || page.Data[0].Preview != "" || page.Data[0].LastMessage != nil || page.Data[0].UnreadCount != 0 {
		t.Fatal("撤回摘要泄漏")
	}
	moderationJobCount(t, s, 0)
}
