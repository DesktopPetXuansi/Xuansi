package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"xuansi/web/backend/internal/platform"
)

// 最小真实会话请求可加入账号护栏，验证跨标签页切换不会首次提交到另一个账号。
func TestPostgresAccountFeedbackStrictInputAndSessionGuard(t *testing.T) {
	s, a := setupModeration(t)
	u := registered(t, s, a, "chat-guard@example.test")
	in := moderationInput("严格账号输入", false)
	delete(in, "managementToken")
	for _, field := range []string{"managementToken", "ownerUserId", "owner_user_id"} {
		in[field] = ""
		messageCall(t, a, "POST", "/api/v1/me/feedback", uuid.NewString(), in, 400)
		delete(in, field)
	}
	body, _ := json.Marshal(in)
	r := httptest.NewRequest("POST", "/api/v1/me/feedback", bytes.NewReader(body))
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", a.csrf)
	r.Header.Set("Idempotency-Key", uuid.NewString())
	r.Header.Set("X-Feedback-Account", uuid.NewString())
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: a.csrf})
	r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: a.session})
	w := httptest.NewRecorder()
	a.handler.ServeHTTP(w, r)
	if w.Code != 409 || !bytes.Contains(w.Body.Bytes(), []byte("ACCOUNT_CHANGED")) {
		t.Fatal("跨账号首次提交未被阻止")
	}
	var n int64
	s.DB.Model(&feedbackEntry{}).Count(&n)
	if n != 0 {
		t.Fatal("账号护栏失败留下收件")
	}
	a.session = ""
	a.call("GET", "/api/v1/me/feedback", nil, 401, "")
	// OAuth中间件对这些路径默认拒绝，额外直接验证路由只接受SessionID。
	h := feedbackWebSession(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Fatal("OAuth通过网站会话护栏") }))
	r = httptest.NewRequest("GET", "/api/v1/me/feedback", nil)
	r = r.WithContext(context.WithValue(r.Context(), identityKey{}, &Identity{User: platform.User{ID: u.ID}, GrantID: uuid.NewString()}))
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 403 {
		t.Fatal("OAuth会话未拒绝")
	}
}

func TestPostgresAccountChatThreadPaginationAndAnonymousCompatibility(t *testing.T) {
	s, a := setupModeration(t)
	user := registered(t, s, a, "chat-pages@example.test")
	now := time.Now().UTC().Truncate(time.Microsecond)
	// 直接播种仅用于验证分页上限和游标，不替代写路径权限测试。
	for i := 0; i < 52; i++ {
		row := feedbackEntry{ID: uuid.NewString(), IdempotencyKey: uuid.NewString(), RequestHash: "synthetic", Category: "BUG", Title: fmt.Sprintf("分页%02d", i), Description: string(bytes.Repeat([]byte("字"), 180)), Status: "NEW", ModerationStatus: "PENDING", CreatedAt: now, UpdatedAt: now.Add(time.Duration(i) * time.Second), OwnerUserID: &user.ID, SubmitterName: "原始昵称"}
		if e := s.DB.Create(&row).Error; e != nil {
			t.Fatal(e)
		}
	}
	var pg struct {
		Data []feedbackThread
		Meta struct{ NextCursor *string }
	}
	raw := a.call("GET", "/api/v1/me/feedback?limit=50", nil, 200, "")
	_ = json.Unmarshal(raw, &pg)
	if len(pg.Data) != 50 || pg.Meta.NextCursor == nil || len([]rune(pg.Data[0].Preview)) != 160 {
		t.Fatal("摘要分页或截断错误")
	}
	cursor := *pg.Meta.NextCursor
	raw = a.call("GET", "/api/v1/me/feedback?limit=50&cursor="+cursor, nil, 200, "")
	pg.Data = nil
	_ = json.Unmarshal(raw, &pg)
	if len(pg.Data) != 2 || pg.Meta.NextCursor != nil {
		t.Fatal("第二页错误")
	}
	a.call("GET", "/api/v1/me/feedback?limit=51", nil, 400, "")
	a.call("GET", "/api/v1/me/feedback?status=RESOLVED&cursor="+cursor, nil, 400, "")
	id := uuid.NewString()
	input := moderationInput("无凭据旧客户端兼容", false)
	delete(input, "managementToken")
	feedbackCall(t, a, id, input, 201)
	a.call("GET", "/api/v1/me/feedback/"+id+"/messages", nil, 404, "")
	a.call("POST", "/api/v1/feedback/"+id+"/messages/query", map[string]string{"managementToken": ""}, 403, "")
	admin := &testClient{t: t, handler: s.Router(), csrf: a.csrf}
	moderationAdmin(t, s, admin)
	view := data[feedbackConversation](t, admin.call("GET", "/api/v1/admin/feedback/"+id+"/messages", nil, 200, ""))
	if view.CanReply {
		t.Fatal("无凭据匿名记录能聊天")
	}
}
