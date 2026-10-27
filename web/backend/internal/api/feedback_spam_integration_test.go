package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/google/uuid"
)

type spamFeedbackPage struct {
	Data []feedbackEntry
	Meta struct{ NextCursor *string }
}

func spamPage(t *testing.T, c *testClient, path string) spamFeedbackPage {
	t.Helper()
	var page spamFeedbackPage
	if err := json.Unmarshal(c.call("GET", path, nil, 200, ""), &page); err != nil {
		t.Fatal(err)
	}
	return page
}

// 审核状态和处理进度独立：标记垃圾后，两个待处理入口都不能继续展示。
func TestPostgresFeedbackSpamLeavesBothAdminInboxes(t *testing.T) {
	s, c := setupModeration(t)
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("待移入垃圾箱的合成反馈", false), 201)
	moderationAdmin(t, s, c)
	c.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	for _, path := range []string{"/api/v1/admin/feedback?status=NEW", "/api/v1/admin/feedback/conversations?status=NEW"} {
		var page struct{ Data []struct{ ID string } }
		if err := json.Unmarshal(c.call("GET", path, nil, 200, ""), &page); err != nil {
			t.Fatal(err)
		}
		if len(page.Data) != 0 {
			t.Fatalf("标垃圾后仍在待处理列表 %s：%+v", path, page.Data)
		}
	}
}

// 垃圾箱收齐不同处理进度，并把分页游标绑定到箱子，保留旧收件游标兼容。
func TestPostgresFeedbackSpamFolderPaginationAndValidation(t *testing.T) {
	s, c := setupModeration(t)
	ids := []string{uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()}
	for i, id := range ids {
		feedbackCall(t, c, id, moderationInput("合成分页反馈"+string(rune('甲'+i)), false), 201)
	}
	moderationAdmin(t, s, c)
	for _, id := range ids[:2] {
		c.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	}
	c.call("PATCH", "/api/v1/admin/feedback/"+ids[1], map[string]string{"status": "RESOLVED"}, 200, "")
	for _, path := range []string{"/api/v1/admin/feedback", "/api/v1/admin/feedback?folder=inbox"} {
		page := spamPage(t, c, path)
		if len(page.Data) != 2 {
			t.Fatalf("普通收件应只含两条正常反馈: %+v", page)
		}
		for _, row := range page.Data {
			if row.ModerationStatus == "SPAM" {
				t.Fatal("垃圾混入普通收件")
			}
		}
	}
	first := spamPage(t, c, "/api/v1/admin/feedback?folder=spam&limit=1")
	if len(first.Data) != 1 || first.Data[0].ModerationStatus != "SPAM" || first.Meta.NextCursor == nil {
		t.Fatalf("垃圾首分页错误: %+v", first)
	}
	second := spamPage(t, c, "/api/v1/admin/feedback?folder=spam&limit=1&cursor="+url.QueryEscape(*first.Meta.NextCursor))
	if len(second.Data) != 1 || second.Data[0].ModerationStatus != "SPAM" || second.Data[0].ID == first.Data[0].ID || second.Meta.NextCursor != nil {
		t.Fatalf("垃圾后续分页错误: %+v", second)
	}
	for _, base := range []string{"/api/v1/admin/feedback?", "/api/v1/admin/feedback/conversations?", "/api/v1/me/feedback?"} {
		c.call("GET", base+"cursor="+url.QueryEscape(*first.Meta.NextCursor), nil, 400, "")
	}
	inbox := spamPage(t, c, "/api/v1/admin/feedback?limit=1")
	if inbox.Meta.NextCursor == nil {
		t.Fatal("缺少普通收件游标")
	}
	// 普通游标不含 folder，可沿用；跨到垃圾箱必须拒绝。
	spamPage(t, c, "/api/v1/admin/feedback?folder=inbox&cursor="+url.QueryEscape(*inbox.Meta.NextCursor))
	c.call("GET", "/api/v1/admin/feedback?folder=spam&cursor="+url.QueryEscape(*inbox.Meta.NextCursor), nil, 400, "")
	for _, folder := range []string{"SPAM", "all", "spam' OR 1=1"} {
		c.call("GET", "/api/v1/admin/feedback?folder="+url.QueryEscape(folder), nil, 400, "")
	}
}

// 清空保留请求收据和账号所有权，擦除全部垃圾正文与私信；正常反馈完全不受影响。
func TestPostgresFeedbackSpamClearPreservesReceiptsAndNormalContent(t *testing.T) {
	s, owner := setupModeration(t)
	registered(t, s, owner, "spam-owner@example.test")
	spamID, normalID, guestID := uuid.NewString(), uuid.NewString(), uuid.NewString()
	spamInput := moderationInput("账号垃圾内容", false)
	delete(spamInput, "managementToken")
	normalInput := moderationInput("正常账号反馈", false)
	delete(normalInput, "managementToken")
	guestInput := moderationInput("匿名垃圾内容", false)
	messageCall(t, owner, "POST", "/api/v1/me/feedback", spamID, spamInput, 201)
	messageCall(t, owner, "POST", "/api/v1/me/feedback", normalID, normalInput, 201)
	guest := &testClient{t: t, handler: s.Router(), csrf: owner.csrf}
	feedbackCall(t, guest, guestID, guestInput, 201)
	spamMessageKey := uuid.NewString()
	spamMessage := data[messageReceipt](t, messageCall(t, owner, "POST", "/api/v1/me/feedback/"+spamID+"/messages", spamMessageKey, map[string]string{"body": "垃圾私信正文"}, 201))
	normalMessage := data[messageReceipt](t, messageCall(t, owner, "POST", "/api/v1/me/feedback/"+normalID+"/messages", uuid.NewString(), map[string]string{"body": "正常私信须保留"}, 201))
	admin := &testClient{t: t, handler: s.Router(), csrf: owner.csrf}
	moderationAdmin(t, s, admin)
	for _, id := range []string{spamID, guestID} {
		admin.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	}
	// 只加载一条垃圾，清空仍须覆盖尚未加载的下一页。
	if page := spamPage(t, admin, "/api/v1/admin/feedback?folder=spam&limit=1"); page.Meta.NextCursor == nil {
		t.Fatal("合成垃圾未形成多页")
	}
	result := data[struct{ ClearedCount int64 }](t, admin.call("DELETE", "/api/v1/admin/feedback/spam", nil, 200, ""))
	if result.ClearedCount != 2 {
		t.Fatalf("只应清空两条垃圾，实际%d", result.ClearedCount)
	}
	for _, id := range []string{spamID, guestID} {
		var stored feedbackEntry
		if err := s.DB.Where("id=?", id).First(&stored).Error; err != nil {
			t.Fatal(err)
		}
		if stored.ClearedAt == nil || stored.ModerationStatus != "SPAM" || stored.Title != "" || stored.Description != "" || stored.Contact != "" || stored.Diagnostics != nil || stored.SubmitterName != "" || stored.RequestHash == "" || stored.IdempotencyKey != id {
			t.Fatalf("垃圾未擦除或幂等骨架丢失: %+v", stored)
		}
	}
	var storedMessage feedbackMessage
	if err := s.DB.Where("id=?", spamMessage.Message.ID).First(&storedMessage).Error; err != nil || storedMessage.Body != "" || storedMessage.AuthorName != "" || storedMessage.RequestHash == "" {
		t.Fatalf("垃圾私信未清空或幂等骨架丢失: %+v %v", storedMessage, err)
	}
	storedMessage = feedbackMessage{}
	if err := s.DB.Where("id=?", normalMessage.Message.ID).First(&storedMessage).Error; err != nil || storedMessage.Body != "正常私信须保留" {
		t.Fatalf("正常私信被误清空: %+v %v", storedMessage, err)
	}
	for _, path := range []string{"/api/v1/admin/feedback", "/api/v1/admin/feedback/conversations", "/api/v1/me/feedback"} {
		client := admin
		if path == "/api/v1/me/feedback" {
			client = owner
		}
		page := spamPage(t, client, path)
		if len(page.Data) != 1 || page.Data[0].ID != normalID {
			t.Fatalf("列表未隔离清空骨架或误删正常反馈 %s: %+v", path, page)
		}
	}
	// 拥有者、管理员及匿名凭据仍要走各自鉴权，但读取都不能返回旧内容。
	for _, raw := range [][]byte{
		owner.call("GET", "/api/v1/me/feedback/"+spamID+"/messages", nil, 200, ""),
		admin.call("GET", "/api/v1/admin/feedback/"+spamID+"/messages", nil, 200, ""),
		guest.call("POST", "/api/v1/feedback/"+guestID+"/messages/query", map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, ""),
	} {
		view := data[feedbackConversation](t, raw)
		if view.Title != "" || view.Description != "" || view.SubmitterName != "" || view.CanReply || view.UnreadCount != 0 || len(view.Messages) != 0 {
			t.Fatalf("直接读取泄漏已清空内容: %s", raw)
		}
	}
	managed := data[moderationManagementView](t, guest.call("POST", "/api/v1/feedback/"+guestID+"/management", map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, ""))
	if managed.CanWithdraw || managed.ModerationStatus != "SPAM" {
		t.Fatalf("清空不应伪装成作者撤回或继续允许撤回: %+v", managed)
	}
	// 原始投稿重试成功回收据，原始消息重试被关闭状态拒绝，都不能复活正文。
	messageCall(t, owner, "POST", "/api/v1/me/feedback", spamID, spamInput, 200)
	feedbackCall(t, guest, guestID, guestInput, 200)
	messageCall(t, owner, "POST", "/api/v1/me/feedback/"+spamID+"/messages", spamMessageKey, map[string]string{"body": "垃圾私信正文"}, 409)
	if page := spamPage(t, admin, "/api/v1/admin/feedback?folder=spam"); len(page.Data) != 0 {
		t.Fatal("已清空垃圾被重试复活")
	}
	repeated := data[struct{ ClearedCount int64 }](t, admin.call("DELETE", "/api/v1/admin/feedback/spam", nil, 200, ""))
	if repeated.ClearedCount != 0 {
		t.Fatal("重复清空不应重复计数")
	}
	var auditCount int64
	if err := s.DB.Table("audit_logs").Where("action='feedback.spam.clear'").Count(&auditCount).Error; err != nil || auditCount != 2 {
		t.Fatalf("清空审计未与操作保存: count=%d err=%v", auditCount, err)
	}
}

// 清空沿用管理员与 CSRF 边界，普通账号或失效请求不能擦除任何垃圾。
func TestPostgresFeedbackSpamClearPermissions(t *testing.T) {
	s, c := setupModeration(t)
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("权限边界合成垃圾", false), 201)
	anonymous := &testClient{t: t, handler: s.Router(), csrf: c.csrf}
	anonymous.call("DELETE", "/api/v1/admin/feedback/spam", nil, 401, "")
	registered(t, s, c, "spam-ordinary@example.test")
	c.call("DELETE", "/api/v1/admin/feedback/spam", nil, 403, "")
	admin := &testClient{t: t, handler: s.Router(), csrf: c.csrf}
	moderationAdmin(t, s, admin)
	admin.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	request := httptest.NewRequest("DELETE", "/api/v1/admin/feedback/spam", nil)
	request.Header.Set("Origin", "http://localhost:3000")
	request.AddCookie(&http.Cookie{Name: "xuansi_session", Value: admin.session})
	w := httptest.NewRecorder()
	admin.handler.ServeHTTP(w, request)
	if w.Code != 403 {
		t.Fatalf("缺失CSRF不应清空垃圾: %d", w.Code)
	}
	if page := spamPage(t, admin, "/api/v1/admin/feedback?folder=spam"); len(page.Data) != 1 {
		t.Fatal("越权请求改变了垃圾箱")
	}
}

// 两个管理员同时清空只能各认领一次，行锁后的条件重检避免重复删除计数。
func TestPostgresFeedbackSpamConcurrentClear(t *testing.T) {
	s, c := setupModeration(t)
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("并发清空合成垃圾", false), 201)
	moderationAdmin(t, s, c)
	c.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	start := make(chan struct{})
	results := make(chan *httptest.ResponseRecorder, 2)
	for range 2 {
		r := httptest.NewRequest("DELETE", "/api/v1/admin/feedback/spam", nil)
		r.Header.Set("Origin", "http://localhost:3000")
		r.Header.Set("X-CSRF-Token", c.csrf)
		r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
		r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: c.session})
		go func() {
			<-start
			w := httptest.NewRecorder()
			c.handler.ServeHTTP(w, r)
			results <- w
		}()
	}
	close(start)
	var total int64
	for range 2 {
		w := <-results
		if w.Code != 200 {
			t.Fatalf("并发清空失败: %d %s", w.Code, w.Body.String())
		}
		total += data[struct{ ClearedCount int64 }](t, w.Body.Bytes()).ClearedCount
	}
	if total != 1 {
		t.Fatalf("并发重复清空同一条垃圾: %d", total)
	}
}

// 已排队但尚未公开的垃圾清空后，原 worker 任务成功结束且不产生外部请求。
func TestPostgresFeedbackSpamClearCancelsQueuedPublication(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken, s.Config.FeedbackGitHubPublic = "synthetic/feedback", "synthetic-token", true
	worker.Config = s.Config
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("排队后移入垃圾箱", true), 201)
	approveFeedbackForDelivery(t, s, c, id)
	c.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "SPAM"}, 200, "")
	c.call("DELETE", "/api/v1/admin/feedback/spam", nil, 200, "")
	var calls atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer remote.Close()
	target, err := url.Parse(remote.URL)
	if err != nil {
		t.Fatal(err)
	}
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}}
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	var status string
	if err := s.DB.Table("jobs").Select("status").Where("kind='FEEDBACK_GITHUB'").Scan(&status).Error; err != nil || status != "DONE" || calls.Load() != 0 {
		t.Fatalf("清空垃圾仍投递或重试任务: status=%s calls=%d err=%v", status, calls.Load(), err)
	}
	if page := spamPage(t, c, "/api/v1/admin/feedback?folder=spam"); len(page.Data) != 0 {
		t.Fatal("投递任务复活已清空垃圾")
	}
	// 管理视图与响应都不暴露清空标记或原凭据。
	raw := c.call("GET", "/api/v1/admin/feedback", nil, 200, "")
	if bytes.Contains(raw, []byte("clearedAt")) || bytes.Contains(raw, []byte("managementToken")) {
		t.Fatal("列表暴露内部清空或管理字段")
	}
}
