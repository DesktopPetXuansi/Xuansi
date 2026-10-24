package api

import (
	"bytes"
	"encoding/json"
	"github.com/google/uuid"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// 独立请求编号与远端地址避开频控干扰，同时测试真实数据库唯一键。
func feedbackCall(t *testing.T, c *testClient, key string, input interface{}, expected int) []byte {
	t.Helper()
	body, _ := json.Marshal(input)
	r := httptest.NewRequest("POST", "/api/v1/feedback", bytes.NewReader(body))
	r.RemoteAddr = "198.51.100.1:8080"
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", c.csrf)
	r.Header.Set("Idempotency-Key", key)
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	w := httptest.NewRecorder()
	c.handler.ServeHTTP(w, r)
	if w.Code != expected {
		t.Fatalf("反馈%d != %d: %s", w.Code, expected, w.Body.String())
	}
	return w.Body.Bytes()
}
func TestPostgresFeedbackPrivateIdempotencyAndPagination(t *testing.T) {
	s, c, _ := setup(t)
	if e := s.DB.Exec("TRUNCATE feedback CASCADE").Error; e != nil {
		t.Fatal(e)
	}
	input := feedbackInput{Category: "BUG", Title: "  出错了  ", Description: "复现步骤", Contact: " mail@example.test ", Diagnostics: &feedbackDiagnostics{AppVersion: "0.8.0", System: "Windows"}}
	key := uuid.NewString()
	first := data[feedbackReceipt](t, feedbackCall(t, c, key, input, 201))
	retry := data[feedbackReceipt](t, feedbackCall(t, c, key, input, 200))
	if first != retry || first.ID != key || first.Status != "NEW" {
		t.Fatalf("收据不稳定: first=%+v retry=%+v key=%s", first, retry, key)
	}
	input.Title = "新内容"
	feedbackCall(t, c, key, input, 409)
	c.call("GET", "/api/v1/admin/feedback", nil, 401, "")
	user := registered(t, s, c, "feedback-admin@example.test")
	c.call("GET", "/api/v1/admin/feedback", nil, 403, "")
	if e := s.DB.Exec("UPDATE users SET role='ADMIN' WHERE id=?", user.ID).Error; e != nil {
		t.Fatal(e)
	}
	row := data[feedbackEntry](t, c.call("PATCH", "/api/v1/admin/feedback/"+first.ID, map[string]string{"status": "IN_PROGRESS"}, 200, ""))
	if row.Status != "IN_PROGRESS" || row.Title != "出错了" || row.Contact != "mail@example.test" || row.Diagnostics == nil || row.Diagnostics.System != "Windows" {
		t.Fatalf("数据不完整%+v", row)
	}
	input.Title = "  出错了  "
	after := data[feedbackReceipt](t, feedbackCall(t, c, key, input, 200))
	if first != after {
		t.Fatal("管理员更新改变了原收据")
	}
	// 分页使用不同内容，避免与持久化的重复内容保护耦合。
	c.handler = s.Router()
	input.Title = "另一条合成反馈"
	feedbackCall(t, c, uuid.NewString(), input, 201)
	input.Title = "第三条合成反馈"
	feedbackCall(t, c, uuid.NewString(), input, 201)
	var page struct {
		Data []feedbackEntry `json:"data"`
		Meta struct {
			NextCursor *string `json:"nextCursor"`
		} `json:"meta"`
	}
	if e := json.Unmarshal(c.call("GET", "/api/v1/admin/feedback?limit=2", nil, 200, ""), &page); e != nil {
		t.Fatal(e)
	}
	if len(page.Data) != 2 || page.Meta.NextCursor == nil {
		t.Fatal("首页或游标缺失")
	}
	seen := map[string]bool{page.Data[0].ID: true, page.Data[1].ID: true}
	cursor := *page.Meta.NextCursor
	if e := json.Unmarshal(c.call("GET", "/api/v1/admin/feedback?limit=2&cursor="+cursor, nil, 200, ""), &page); e != nil {
		t.Fatal(e)
	}
	if len(page.Data) != 1 || page.Meta.NextCursor != nil || seen[page.Data[0].ID] {
		t.Fatal("分页重复或遗漏")
	}
	c.call("GET", "/api/v1/admin/feedback?status=NEW&cursor="+cursor, nil, 400, "")
	for _, q := range []string{"status=BAD", "limit=0", "limit=101", "cursor=bad"} {
		c.call("GET", "/api/v1/admin/feedback?"+q, nil, 400, "")
	}
	c.call("PATCH", "/api/v1/admin/feedback/"+first.ID, map[string]string{"status": "BAD"}, 400, "")
	c.call("PATCH", "/api/v1/admin/feedback/"+first.ID, map[string]string{"status": "RESOLVED", "contact": "overwrite"}, 400, "")
	c.call("PATCH", "/api/v1/admin/feedback/"+uuid.NewString(), map[string]string{"status": "RESOLVED"}, 404, "")
	c.call("PATCH", "/api/v1/admin/feedback/"+first.ID, map[string]string{"status": "RESOLVED"}, 200, "")
	filtered := data[[]feedbackEntry](t, c.call("GET", "/api/v1/admin/feedback?status=RESOLVED", nil, 200, ""))
	if len(filtered) != 1 || filtered[0].ID != first.ID {
		t.Fatal("状态筛选无效")
	}
	raw := feedbackCall(t, c, uuid.NewString(), feedbackInput{Category: "OTHER", Title: "标题", Description: "正文"}, 201)
	var receipt struct {
		Data map[string]json.RawMessage `json:"data"`
	}
	if e := json.Unmarshal(raw, &receipt); e != nil {
		t.Fatal(e)
	}
	if len(receipt.Data) != 3 {
		t.Fatal("收据泄漏私有字段")
	}
}

// 并发重试落在同一数据库唯一键，只允许一个首次创建且收据完全一致。
func TestPostgresFeedbackConcurrentRetries(t *testing.T) {
	s, _, _ := setup(t)
	key := uuid.NewString()
	input := feedbackInput{Category: "SUGGESTION", Title: "建议", Description: "改进操作"}
	body, _ := json.Marshal(input)
	results := make(chan *httptest.ResponseRecorder, 8)
	for i := 0; i < 8; i++ {
		go func() {
			r := httptest.NewRequest("POST", "/api/v1/feedback", bytes.NewReader(body))
			r.Header.Set("Idempotency-Key", key)
			w := httptest.NewRecorder()
			s.createFeedback(w, r)
			results <- w
		}()
	}
	created := 0
	var first []byte
	for i := 0; i < 8; i++ {
		w := <-results
		if w.Code == 201 {
			created++
		} else if w.Code != 200 {
			t.Fatalf("并发写入%d %s", w.Code, w.Body.String())
		}
		if first == nil {
			first = append([]byte{}, w.Body.Bytes()...)
		} else if !bytes.Equal(first, w.Body.Bytes()) {
			t.Fatal("并发收据不一致")
		}
	}
	if created != 1 {
		t.Fatalf("首次创建数%d", created)
	}
	var count int64
	if e := s.DB.Table("feedback").Where("idempotency_key=?", key).Count(&count).Error; e != nil || count != 1 {
		t.Fatalf("重复记录 %d %v", count, e)
	}
}

// 存储失败必须返回失败收据，固定事件日志不含用户正文或数据库错误。
func TestPostgresFeedbackStorageFailureDoesNotLeakInput(t *testing.T) {
	s, c, _ := setup(t)
	var log bytes.Buffer
	s.Log = slog.New(slog.NewTextHandler(&log, nil))
	c.handler = s.Router()
	sql, e := s.DB.DB()
	if e != nil {
		t.Fatal(e)
	}
	if e = sql.Close(); e != nil {
		t.Fatal(e)
	}
	secret := "private-feedback-body@example.test"
	feedbackCall(t, c, uuid.NewString(), feedbackInput{Category: "BUG", Title: secret, Description: secret, Contact: secret, Diagnostics: &feedbackDiagnostics{System: secret}}, 500)
	if strings.Contains(log.String(), secret) || !strings.Contains(log.String(), "反馈存储操作失败") {
		t.Fatalf("日志未遵守隐私边界: %s", log.String())
	}
}
