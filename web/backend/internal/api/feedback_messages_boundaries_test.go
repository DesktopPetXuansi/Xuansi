package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm/clause"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
	"xuansi/web/backend/internal/platform"
)

func conversationFixture(t *testing.T) (*Server, *testClient, string, string) {
	t.Helper()
	s, c := setupModeration(t)
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("对话边界合成问题", false), 201)
	return s, c, id, strings.Repeat("a", 64)
}
func TestPostgresMessagesAuthenticationAndClosedStates(t *testing.T) {
	s, c, id, token := conversationFixture(t)
	path := "/api/v1/feedback/" + id + "/messages"
	for _, badID := range []string{"bad", uuid.NewString(), id} {
		badToken := strings.Repeat("b", 64)
		raw := c.call("POST", "/api/v1/feedback/"+badID+"/messages/query", map[string]string{"managementToken": badToken}, 403, "")
		if !bytes.Contains(raw, []byte("INVALID_MANAGEMENT_TOKEN")) {
			t.Fatal("匿名凭据错误不统一")
		}
	}
	registered(t, s, c, "ordinary@example.test")
	c.call("GET", "/api/v1/admin/feedback/"+id+"/messages", nil, 403, "")
	c.call("POST", "/api/v1/admin/feedback/"+id+"/messages", map[string]string{"body": "无权限"}, 403, "")
	for _, state := range []string{"SPAM", "WITHDRAWAL_REQUESTED", "WITHDRAWN"} {
		if e := s.DB.Model(&feedbackEntry{}).Where("id=?", id).Update("moderation_status", state).Error; e != nil {
			t.Fatal(e)
		}
		messageCall(t, c, "POST", path, uuid.NewString(), map[string]string{"managementToken": token, "body": "已关闭"}, 409)
		var view struct{ Data struct{ CanReply bool } }
		raw := c.call("POST", path+"/query", map[string]string{"managementToken": token}, 200, "")
		_ = json.Unmarshal(raw, &view)
		if view.Data.CanReply {
			t.Fatal("关闭状态仍可回复")
		}
	}
	if e := s.DB.Model(&feedbackEntry{}).Where("id=?", id).Updates(map[string]interface{}{"moderation_status": "PENDING", "management_token_hash": ""}).Error; e != nil {
		t.Fatal(e)
	}
	moderationAdmin(t, s, c)
	adminPath := "/api/v1/admin/feedback/" + id + "/messages"
	messageCall(t, c, "POST", adminPath, uuid.NewString(), map[string]string{"body": "旧反馈"}, 409)
	c.call("GET", "/api/v1/admin/feedback/"+uuid.NewString()+"/messages", nil, 404, "")
}
func TestPostgresMessagesStrictInputAndPagination(t *testing.T) {
	s, c, id, token := conversationFixture(t)
	path := "/api/v1/feedback/" + id + "/messages"
	for _, input := range []interface{}{map[string]string{"managementToken": token, "body": " "}, map[string]string{"managementToken": token, "body": strings.Repeat("字", 4001)}, map[string]string{"managementToken": token, "body": "正文", "resolve": "true"}, map[string]string{"managementToken": token, "body": "正文", "extra": "secret"}} {
		messageCall(t, c, "POST", path, uuid.NewString(), input, 400)
	}
	messageCall(t, c, "POST", path, "bad", map[string]string{"managementToken": token, "body": "正文"}, 400)
	for _, limit := range []int{0, 51, -1} {
		c.call("POST", path+"/query", map[string]interface{}{"managementToken": token, "limit": limit}, 400, "")
	}
	c.call("POST", path+"/query", map[string]string{"managementToken": token, "cursor": "bad"}, 400, "")
	// 直接播种多条消息只为分页边界，不绕过写入行为测试。
	now := time.Now().UTC().Truncate(time.Microsecond)
	for i := 0; i < 23; i++ {
		row := feedbackMessage{ID: uuid.NewString(), FeedbackID: id, AuthorRole: "ADMIN", Body: fmt.Sprintf("合成分页 %02d", i), CreatedAt: now.Add(time.Duration(i) * time.Second), IdempotencyKey: uuid.NewString(), RequestHash: strings.Repeat("c", 64)}
		if e := s.DB.Create(&row).Error; e != nil {
			t.Fatal(e)
		}
	}
	var page struct {
		Data struct{ Messages []feedbackMessage }
		Meta struct{ NextCursor *string }
	}
	raw := c.call("POST", path+"/query", map[string]string{"managementToken": token}, 200, "")
	_ = json.Unmarshal(raw, &page)
	if len(page.Data.Messages) != 20 || page.Data.Messages[0].Body != "合成分页 03" || page.Meta.NextCursor == nil {
		t.Fatalf("默认分页错误 %s", raw)
	}
	cursor := *page.Meta.NextCursor
	raw = c.call("POST", path+"/query", map[string]string{"managementToken": token, "cursor": cursor}, 200, "")
	_ = json.Unmarshal(raw, &page)
	if len(page.Data.Messages) != 3 || page.Data.Messages[2].Body != "合成分页 02" || page.Meta.NextCursor != nil {
		t.Fatalf("早期分页错误 %s", raw)
	}
	other := uuid.NewString()
	feedbackCall(t, c, other, moderationInput("游标绑定其他问题", false), 201)
	c.call("POST", "/api/v1/feedback/"+other+"/messages/query", map[string]string{"managementToken": token, "cursor": cursor}, 400, "")
}
func TestPostgresMessagesIdempotencyQuotaAndStatus(t *testing.T) {
	s, c, id, token := conversationFixture(t)
	path := "/api/v1/feedback/" + id + "/messages"
	key := uuid.NewString()
	input := map[string]string{"managementToken": token, "body": "第一条"}
	messageCall(t, c, "POST", path, key, input, 201)
	for i := 0; i < 4; i++ {
		messageCall(t, c, "POST", path, uuid.NewString(), map[string]string{"managementToken": token, "body": fmt.Sprintf("补充%d", i)}, 201)
	}
	messageCall(t, c, "POST", path, uuid.NewString(), input, 429)
	messageCall(t, c, "POST", path, key, input, 200)
	messageCall(t, c, "POST", path, key, map[string]string{"managementToken": token, "body": "冲突"}, 409)
	// 新反馈额度与私信独立，发送消息耗尽不妨碍创建新反馈。
	feedbackCall(t, c, uuid.NewString(), moderationInput("独立初始额度", false), 201)
	moderationAdmin(t, s, c)
	adminPath := "/api/v1/admin/feedback/" + id + "/messages"
	adminKey := uuid.NewString()
	first := messageCall(t, c, "POST", adminPath, adminKey, map[string]string{"body": "普通回复"}, 201)
	var receipt struct {
		Data struct{ FeedbackStatus string }
	}
	_ = json.Unmarshal(first, &receipt)
	if receipt.Data.FeedbackStatus != "IN_PROGRESS" {
		t.Fatal("普通回复未开始处理")
	}
	messageCall(t, c, "POST", adminPath, adminKey, map[string]interface{}{"body": "普通回复", "resolve": true}, 409)
	messageCall(t, c, "POST", adminPath, uuid.NewString(), map[string]interface{}{"body": "已解决", "resolve": true}, 201)
	replay := messageCall(t, c, "POST", adminPath, adminKey, map[string]string{"body": "普通回复"}, 200)
	firstReceipt := data[messageReceipt](t, first)
	retryReceipt := data[messageReceipt](t, replay)
	if firstReceipt.Message != retryReceipt.Message || retryReceipt.FeedbackStatus != "RESOLVED" {
		t.Fatal("重试消息改变或未返回当前进度")
	}
	var row feedbackEntry
	_ = s.DB.Where("id=?", id).First(&row).Error
	if row.Status != "RESOLVED" {
		t.Fatal("重放修改后续状态")
	}
	// 真实操作者不同，即使正文相同也不能重用另一管理员的请求编号。
	u := registered(t, s, c, "second-admin@example.test")
	_ = s.DB.Model(&platform.User{}).Where("id=?", u.ID).Update("role", "ADMIN").Error
	messageCall(t, c, "POST", adminPath, adminKey, map[string]string{"body": "普通回复"}, 409)
}

// 持父行锁让撤回先提交，发送和读取必须等待，随后不能返回或恢复正文。
func TestPostgresMessagesWithdrawalLockAndImmediateRedaction(t *testing.T) {
	s, c, id, token := conversationFixture(t)
	path := "/api/v1/feedback/" + id + "/messages"
	messageCall(t, c, "POST", path, uuid.NewString(), map[string]string{"managementToken": token, "body": "应被清理的私信"}, 201)
	tx := s.DB.Begin()
	if tx.Error != nil {
		t.Fatal(tx.Error)
	}
	defer tx.Rollback()
	var row feedbackEntry
	if e := tx.Clauses(clause.Locking{Strength: "UPDATE"}).Where("id=?", id).First(&row).Error; e != nil {
		t.Fatal(e)
	}
	row.ModerationStatus = "WITHDRAWAL_REQUESTED"
	if e := saveFeedbackWithdrawal(tx, &row); e != nil {
		t.Fatal(e)
	}
	run := func(write bool) chan *httptest.ResponseRecorder {
		done := make(chan *httptest.ResponseRecorder, 1)
		go func() {
			body, _ := json.Marshal(map[string]string{"managementToken": token, "body": "不应恢复"})
			if !write {
				body, _ = json.Marshal(map[string]string{"managementToken": token})
			}
			r := httptest.NewRequest("POST", path, bytes.NewReader(body))
			r.Header.Set("Idempotency-Key", uuid.NewString())
			rc := chi.NewRouteContext()
			rc.URLParams.Add("id", id)
			r = r.WithContext(context.WithValue(r.Context(), chi.RouteCtxKey, rc))
			w := httptest.NewRecorder()
			if write {
				s.sendUserFeedbackMessage(w, r)
			} else {
				s.queryFeedbackMessages(w, r)
			}
			done <- w
		}()
		return done
	}
	readDone, writeDone := run(false), run(true)
	select {
	case <-readDone:
		t.Fatal("读取未等待父锁")
	case <-writeDone:
		t.Fatal("发送未等待父锁")
	case <-time.After(100 * time.Millisecond):
	}
	if e := tx.Commit().Error; e != nil {
		t.Fatal(e)
	}
	for _, test := range []struct {
		done   chan *httptest.ResponseRecorder
		status int
	}{{readDone, 200}, {writeDone, 409}} {
		select {
		case w := <-test.done:
			if w.Code != test.status || bytes.Contains(w.Body.Bytes(), []byte("应被清理")) {
				t.Fatalf("锁后响应异常 %d %s", w.Code, w.Body.String())
			}
		case <-time.After(3 * time.Second):
			t.Fatal("锁释放未完成")
		}
	}
	var count int64
	_ = s.DB.Model(&feedbackMessage{}).Where("feedback_id=? AND body<>''", id).Count(&count).Error
	if count != 0 {
		t.Fatal("首次撤回未清空私信")
	}
}

// 本地事务错误不能留下消息而缺少对应状态或审计。
func TestPostgresMessagesAuditFailureRollsBack(t *testing.T) {
	s, c, id, _ := conversationFixture(t)
	moderationAdmin(t, s, c)
	if e := s.DB.Exec(`CREATE FUNCTION test_reject_message_audit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action LIKE 'feedback.message.%' THEN RAISE EXCEPTION 'synthetic audit failure'; END IF; RETURN NEW; END $$; CREATE TRIGGER test_message_audit BEFORE INSERT ON audit_logs FOR EACH ROW EXECUTE FUNCTION test_reject_message_audit()`).Error; e != nil {
		t.Fatal(e)
	}
	defer s.DB.Exec(`DROP TRIGGER IF EXISTS test_message_audit ON audit_logs; DROP FUNCTION IF EXISTS test_reject_message_audit()`)
	messageCall(t, c, "POST", "/api/v1/admin/feedback/"+id+"/messages", uuid.NewString(), map[string]string{"body": "必须整体回滚"}, 500)
	var count int64
	_ = s.DB.Model(&feedbackMessage{}).Where("feedback_id=?", id).Count(&count).Error
	var row feedbackEntry
	_ = s.DB.Where("id=?", id).First(&row).Error
	if count != 0 || row.Status != "NEW" {
		t.Fatal("消息事务部分保存")
	}
}

// 模拟已经验证的 OAuth 身份，确认即使账号为 ADMIN，客户端授权仍不能进入后台。
type messageGrantAuthenticator struct {
	OAuthService
	userID string
}

func (a messageGrantAuthenticator) Authenticate(context.Context, string) (string, string, []string, error) {
	return a.userID, uuid.NewString(), []string{"resources:read", "resources:write", "history:read", "history:write"}, nil
}
func TestPostgresMessagesRejectAdminOAuthGrant(t *testing.T) {
	s, c, id, _ := conversationFixture(t)
	moderationAdmin(t, s, c)
	var user platform.User
	if e := s.DB.Where("role='ADMIN'").First(&user).Error; e != nil {
		t.Fatal(e)
	}
	s.OAuth = messageGrantAuthenticator{userID: user.ID}
	c.handler = s.Router()
	path := "/api/v1/admin/feedback/" + id + "/messages"
	c.call("GET", path, nil, 403, "synthetic-access-token")
	c.call("POST", path, map[string]string{"body": "不应写入"}, 403, "synthetic-access-token")
}
