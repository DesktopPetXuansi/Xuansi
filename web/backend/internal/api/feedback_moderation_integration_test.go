package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"xuansi/web/backend/internal/platform"
)

// 管理契约只依赖公开 JSON，避免测试与实现内部的状态视图类型绑定。
type moderationManagementView struct {
	ID               string `json:"id"`
	ModerationStatus string `json:"moderationStatus"`
	CanWithdraw      bool   `json:"canWithdraw"`
}

func setupModeration(t *testing.T) (*Server, *testClient) {
	t.Helper()
	s, c, _ := setup(t)
	if err := s.DB.Exec("TRUNCATE feedback,feedback_submission_limits CASCADE").Error; err != nil {
		t.Fatal(err)
	}
	s.Config.FeedbackGitHubRepository = "synthetic/feedback"
	s.Config.FeedbackGitHubToken = "synthetic-token"
	s.Config.FeedbackGitHubPublic = true
	c.handler = s.Router()
	return s, c
}

func moderationInput(title string, consent bool) map[string]interface{} {
	return map[string]interface{}{
		"category": "BUG", "title": title, "description": "合成复现步骤：" + title,
		"contact": "synthetic@example.test", "diagnostics": map[string]string{"system": "synthetic-system"},
		"publicConsent": consent, "managementToken": strings.Repeat("a", 64),
	}
}

func moderationJobCount(t *testing.T, s *Server, expected int64) {
	t.Helper()
	var count int64
	if err := s.DB.Table("jobs").Where("kind='FEEDBACK_GITHUB'").Count(&count).Error; err != nil || count != expected {
		t.Fatalf("投递任务数=%d，期望%d，错误=%v", count, expected, err)
	}
}

func moderationAdmin(t *testing.T, s *Server, c *testClient) {
	t.Helper()
	u := registered(t, s, c, "moderation-admin@example.test")
	if err := s.DB.Exec("UPDATE users SET role='ADMIN' WHERE id=?", u.ID).Error; err != nil {
		t.Fatal(err)
	}
}

// 不论是否启用 GitHub，匿名提交都只能先进入私有收件；凭据和访客摘要不属于管理员数据。
func TestPostgresModerationPrivateCreationAndCredentialBoundary(t *testing.T) {
	s, c := setupModeration(t)
	key := uuid.NewString()
	input := moderationInput("待审核合成反馈", true)
	feedbackCall(t, c, key, input, http.StatusCreated)
	moderationJobCount(t, s, 0)
	var row struct{ ManagementTokenHash, ModerationStatus, ClientHash, ContentHash string }
	if err := s.DB.Table("feedback").Where("id=?", key).First(&row).Error; err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256([]byte(strings.Repeat("a", 64)))
	if row.ModerationStatus != "PENDING" || row.ManagementTokenHash != hex.EncodeToString(hash[:]) || row.ClientHash == "" || row.ContentHash == "" {
		t.Fatalf("私有收件或凭据摘要错误: %+v", row)
	}
	path := "/api/v1/feedback/" + key + "/management"
	c.call("POST", path, map[string]string{}, 403, "")
	c.call("POST", path, map[string]string{"managementToken": strings.Repeat("b", 64)}, 403, "")
	managementRaw := c.call("POST", path, map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, "")
	for _, private := range []string{"synthetic@example.test", "synthetic-system", "合成复现步骤", strings.Repeat("a", 64), row.ManagementTokenHash} {
		if bytes.Contains(managementRaw, []byte(private)) {
			t.Fatalf("管理视图泄漏私有提交或凭据: %s", managementRaw)
		}
	}
	managed := data[moderationManagementView](t, managementRaw)
	if managed.ID != key || managed.ModerationStatus != "PENDING" || !managed.CanWithdraw {
		t.Fatalf("匿名管理视图错误: %+v", managed)
	}
	// 管理权限属于单条记录，另一条反馈的正确凭据不能跨编号使用。
	otherKey, otherInput := uuid.NewString(), moderationInput("另一条独立凭据反馈", true)
	otherInput["managementToken"] = strings.Repeat("b", 64)
	feedbackCall(t, c, otherKey, otherInput, 201)
	for _, action := range []string{"management", "withdrawal"} {
		c.call("POST", "/api/v1/feedback/"+otherKey+"/"+action, map[string]string{"managementToken": strings.Repeat("a", 64)}, 403, "")
	}
	moderationAdmin(t, s, c)
	raw := c.call("GET", "/api/v1/admin/feedback", nil, 200, "")
	for _, secret := range []string{strings.Repeat("a", 64), row.ManagementTokenHash, row.ClientHash, row.ContentHash, "managementToken"} {
		if bytes.Contains(raw, []byte(secret)) {
			t.Fatalf("管理员响应泄漏管理或访客凭据: %s", raw)
		}
	}
}

// 十个独立路由模拟多个进程共享数据库，不能靠各自的内存计数突破分钟额度。
func TestPostgresModerationConcurrentPersistentQuota(t *testing.T) {
	s, c := setupModeration(t)
	results := make(chan *httptest.ResponseRecorder, 10)
	start := make(chan struct{})
	for i := 0; i < 10; i++ {
		handler := s.Router()
		body, err := json.Marshal(moderationInput(fmt.Sprintf("并发持久额度%d", i), true))
		if err != nil {
			t.Fatal(err)
		}
		r := httptest.NewRequest("POST", "/api/v1/feedback", bytes.NewReader(body))
		r.RemoteAddr = "198.51.100.1:8080"
		r.Header.Set("Origin", "http://localhost:3000")
		r.Header.Set("X-CSRF-Token", c.csrf)
		r.Header.Set("Idempotency-Key", uuid.NewString())
		r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
		go func() {
			<-start
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			results <- w
		}()
	}
	close(start)
	created, limited := 0, 0
	for i := 0; i < 10; i++ {
		select {
		case w := <-results:
			switch w.Code {
			case 201:
				created++
			case 429:
				limited++
			default:
				t.Fatalf("并发额度异常响应: %d %s", w.Code, w.Body.String())
			}
		case <-time.After(10 * time.Second):
			t.Fatal("并发持久额度未在期限内完成")
		}
	}
	if created != 5 || limited != 5 {
		t.Fatalf("并发突破分钟额度: created=%d limited=%d", created, limited)
	}
	var count int64
	if err := s.DB.Table("feedback").Count(&count).Error; err != nil || count != 5 {
		t.Fatalf("并发额度失败请求未回滚收件: count=%d err=%v", count, err)
	}
}

// 只推进分钟窗口，小时窗口仍应累计二十条；失败请求不能保存反馈。
func TestPostgresModerationHourQuotaSurvivesMinuteResets(t *testing.T) {
	s, c := setupModeration(t)
	for i := 0; i < 20; i++ {
		if i > 0 && i%5 == 0 {
			if err := s.DB.Exec("UPDATE feedback_submission_limits SET resets_at=now()-interval '1 second' WHERE window_kind='MINUTE'").Error; err != nil {
				t.Fatal(err)
			}
		}
		c.handler = s.Router()
		feedbackCall(t, c, uuid.NewString(), moderationInput(fmt.Sprintf("跨分钟小时额度%d", i), true), 201)
	}
	if err := s.DB.Exec("UPDATE feedback_submission_limits SET resets_at=now()-interval '1 second' WHERE window_kind='MINUTE'").Error; err != nil {
		t.Fatal(err)
	}
	c.handler = s.Router()
	feedbackCall(t, c, uuid.NewString(), moderationInput("第二十一条仍受小时额度限制", true), 429)
	var count int64
	if err := s.DB.Table("feedback").Count(&count).Error; err != nil || count != 20 {
		t.Fatalf("小时额度未持久累计: count=%d err=%v", count, err)
	}
}

// 撤回删除敏感内容，原提交的幂等重试不能复活正文或重新排队。
func TestPostgresModerationWithdrawalRedactsAndRetryCannotRestore(t *testing.T) {
	s, c := setupModeration(t)
	key, input := uuid.NewString(), moderationInput("可撤回合成反馈", true)
	receipt := feedbackCall(t, c, key, input, 201)
	path := "/api/v1/feedback/" + key + "/withdrawal"
	c.call("POST", path, map[string]string{}, 403, "")
	c.call("POST", path, map[string]string{"managementToken": strings.Repeat("b", 64)}, 403, "")
	for i := 0; i < 2; i++ {
		view := data[moderationManagementView](t, c.call("POST", path, map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, ""))
		if view.ModerationStatus != "WITHDRAWN" || view.CanWithdraw {
			t.Fatalf("撤回非幂等: %+v", view)
		}
	}
	if retry := feedbackCall(t, c, key, input, 200); !bytes.Equal(receipt, retry) {
		t.Fatal("撤回后的原 POST 重试改变了收据")
	}
	var row struct {
		Title, Description, Contact, ModerationStatus string
		Diagnostics                                   json.RawMessage
	}
	if err := s.DB.Table("feedback").Where("id=?", key).First(&row).Error; err != nil {
		t.Fatal(err)
	}
	if row.Title != "" || row.Description != "" || row.Contact != "" || (len(row.Diagnostics) != 0 && string(row.Diagnostics) != "null") || row.ModerationStatus != "WITHDRAWN" {
		t.Fatalf("撤回未清理正文/联系方式/诊断: %+v", row)
	}
	moderationJobCount(t, s, 0)
	moderationAdmin(t, s, c)
	c.call("POST", "/api/v1/admin/feedback/"+key+"/moderation", map[string]string{"decision": "APPROVE"}, 409, "")
	moderationJobCount(t, s, 0)
}

// 公开必须同时满足管理员审核、作者许可；重复批准只能保留一份持久投递责任。
func TestPostgresModerationApprovalPermissionsConsentAndUniqueQueue(t *testing.T) {
	s, c := setupModeration(t)
	key := uuid.NewString()
	feedbackCall(t, c, key, moderationInput("许可公开的合成反馈", true), 201)
	path := "/api/v1/admin/feedback/" + key + "/moderation"
	c.call("POST", path, map[string]string{"decision": "APPROVE"}, 401, "")
	u := registered(t, s, c, "moderation-user@example.test")
	c.call("POST", path, map[string]string{"decision": "APPROVE"}, 403, "")
	if err := s.DB.Exec("UPDATE users SET role='ADMIN' WHERE id=?", u.ID).Error; err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		view := data[struct {
			ModerationStatus string `json:"moderationStatus"`
		}](t, c.call("POST", path, map[string]string{"decision": "APPROVE"}, 200, ""))
		if view.ModerationStatus != "APPROVED" {
			t.Fatalf("审核状态未批准: %+v", view)
		}
		moderationJobCount(t, s, 1)
	}
	privateKey := uuid.NewString()
	feedbackCall(t, c, privateKey, moderationInput("未许可公开的合成反馈", false), 201)
	c.call("POST", "/api/v1/admin/feedback/"+privateKey+"/moderation", map[string]string{"decision": "APPROVE"}, 409, "")
	moderationJobCount(t, s, 1)
	// 审核后尚未开始投递仍可撤回；取消后不得再次批准。
	c.call("POST", "/api/v1/feedback/"+key+"/withdrawal", map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, "")
	c.call("POST", path, map[string]string{"decision": "APPROVE"}, 409, "")
}

// 用独立事务占住行锁，模拟投递刚开始；撤回必须等待并观察提交后的公开边界。
func TestPostgresModerationWithdrawalWaitsForPublicationRowLock(t *testing.T) {
	s, c := setupModeration(t)
	key := uuid.NewString()
	feedbackCall(t, c, key, moderationInput("投递竞态合成反馈", true), 201)
	moderationAdmin(t, s, c)
	c.call("POST", "/api/v1/admin/feedback/"+key+"/moderation", map[string]string{"decision": "APPROVE"}, 200, "")
	tx := s.DB.Begin()
	if tx.Error != nil {
		t.Fatal(tx.Error)
	}
	defer tx.Rollback()
	if err := tx.Exec("UPDATE feedback SET publication_started_at=now() WHERE id=?", key).Error; err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"managementToken": strings.Repeat("a", 64)})
	r := httptest.NewRequest("POST", "/api/v1/feedback/"+key+"/withdrawal", bytes.NewReader(body))
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", c.csrf)
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	response := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		w := httptest.NewRecorder()
		c.handler.ServeHTTP(w, r)
		response <- w
	}()
	select {
	case w := <-response:
		t.Fatalf("撤回绕过了投递事务行锁: %d %s", w.Code, w.Body.String())
	case <-time.After(100 * time.Millisecond):
	}
	if err := tx.Commit().Error; err != nil {
		t.Fatal(err)
	}
	select {
	case w := <-response:
		if w.Code != 200 {
			t.Fatalf("竞态撤回返回%d: %s", w.Code, w.Body.String())
		}
		view := data[moderationManagementView](t, w.Body.Bytes())
		if view.ModerationStatus != "WITHDRAWAL_REQUESTED" {
			t.Fatalf("已开始公开却宣称完成撤回: %+v", view)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("行锁释放后撤回仍未结束")
	}
	// 请求撤回后保留管理员清理所需信息，不能假装从未公开。
	var description string
	if err := s.DB.Table("feedback").Select("description").Where("id=?", key).Scan(&description).Error; err != nil || description == "" {
		t.Fatalf("公开撤回申请意外清理了审核上下文: %v", err)
	}
}

// 服务重建不能重置数据库防刷；重复内容更换幂等键也不能绕过。
func TestPostgresModerationPersistentQuotaDuplicateAndFreeRetry(t *testing.T) {
	s, c := setupModeration(t)
	key, input := uuid.NewString(), moderationInput("频控合成反馈0", true)
	feedbackCall(t, c, key, input, 201)
	// 重建路由排除内存限制对数据库配额断言的影响。
	for i := 0; i < 6; i++ {
		c.handler = s.Router()
		feedbackCall(t, c, key, input, 200)
	}
	c.handler = s.Router()
	feedbackCall(t, c, uuid.NewString(), input, 409)
	for i := 1; i < 5; i++ {
		c.handler = s.Router()
		feedbackCall(t, c, uuid.NewString(), moderationInput(fmt.Sprintf("频控合成反馈%d", i), true), 201)
	}
	c.handler = s.Router()
	feedbackCall(t, c, uuid.NewString(), moderationInput("第六条应该被限流", true), 429)
	// 额度已满时重试既有请求仍然成功。
	c.handler = s.Router()
	feedbackCall(t, c, key, input, 200)
	var count int64
	if err := s.DB.Table("feedback").Count(&count).Error; err != nil || count != 5 {
		t.Fatalf("持久配额或幂等重试错误: count=%d err=%v", count, err)
	}
}

// 垃圾反馈不能被误批准；撤回已审核但尚未出网的任务必须让 Worker 静默跳过。
func TestPostgresModerationSpamAndWithdrawalCancelPendingDelivery(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken, s.Config.FeedbackGitHubPublic = "synthetic/feedback", "synthetic-token", true
	worker.Config = s.Config
	spamKey := uuid.NewString()
	feedbackCall(t, c, spamKey, moderationInput("合成垃圾内容", true), 201)
	moderationAdmin(t, s, c)
	if err := s.DB.Exec("DELETE FROM jobs WHERE kind='MAIL'").Error; err != nil {
		t.Fatal(err)
	}
	path := "/api/v1/admin/feedback/" + spamKey + "/moderation"
	row := data[struct {
		ModerationStatus string `json:"moderationStatus"`
	}](t, c.call("POST", path, map[string]string{"decision": "SPAM"}, 200, ""))
	if row.ModerationStatus != "SPAM" {
		t.Fatalf("垃圾标记未保存: %+v", row)
	}
	c.call("POST", path, map[string]string{"decision": "APPROVE"}, 409, "")
	moderationJobCount(t, s, 0)
	key := uuid.NewString()
	feedbackCall(t, c, key, moderationInput("合成撤回排队任务", true), 201)
	approveFeedbackForDelivery(t, s, c, key)
	moderationJobCount(t, s, 1)
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
	view := data[moderationManagementView](t, c.call("POST", "/api/v1/feedback/"+key+"/withdrawal", map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, ""))
	if view.ModerationStatus != "WITHDRAWN" {
		t.Fatalf("排队期间不能完整撤回: %+v", view)
	}
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 0 {
		t.Fatalf("撤回排队反馈后仍有%d次外部请求", calls.Load())
	}
}

// 真实投递停在创建 Issue 的网络边界：管理员不能抢先确认撤回并擦掉随后到达的公开收据。
func TestPostgresModerationInFlightPublicationRequiresCompletedCleanup(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken, s.Config.FeedbackGitHubPublic = "synthetic/feedback", "synthetic-token", true
	worker.Config = s.Config
	key := uuid.NewString()
	feedbackCall(t, c, key, moderationInput("合成投递中撤回竞态", true), 201)
	approveFeedbackForDelivery(t, s, c, key)
	entered, release := make(chan struct{}, 1), make(chan struct{})
	var releaseOnce sync.Once
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.Method == "GET" && r.URL.Path == "/repos/synthetic/feedback":
			fmt.Fprint(w, `{"private":false,"has_issues":true}`)
		case r.Method == "GET" && r.URL.Path == "/repos/synthetic/feedback/issues":
			fmt.Fprint(w, `[]`)
		case r.Method == "POST" && r.URL.Path == "/repos/synthetic/feedback/issues":
			entered <- struct{}{}
			select {
			case <-release:
				w.WriteHeader(http.StatusCreated)
				fmt.Fprint(w, `{"number":93,"html_url":"https://github.com/synthetic/feedback/issues/93"}`)
			case <-r.Context().Done():
				return
			}
		default:
			http.NotFound(w, r)
		}
	}))
	defer func() {
		releaseOnce.Do(func() { close(release) })
		remote.Close()
	}()
	target, err := url.Parse(remote.URL)
	if err != nil {
		t.Fatal(err)
	}
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}, Timeout: 10 * time.Second}
	done := make(chan error, 1)
	go func() { done <- worker.Tick(context.Background()) }()
	select {
	case <-entered:
	case err := <-done:
		t.Fatalf("尚未进入合成 Issue 创建即结束: %v", err)
	case <-time.After(5 * time.Second):
		t.Fatal("Worker 没有进入合成 Issue 创建阶段")
	}
	// 不带管理员 session，凭每条反馈的管理凭据行使匿名撤回权。
	anonymous := &testClient{t: t, handler: s.Router(), csrf: c.csrf}
	view := data[moderationManagementView](t, anonymous.call("POST", "/api/v1/feedback/"+key+"/withdrawal", map[string]string{"managementToken": strings.Repeat("a", 64)}, 200, ""))
	if view.ModerationStatus != "WITHDRAWAL_REQUESTED" {
		t.Fatalf("投递已经开始却宣称完成撤回: %+v", view)
	}
	moderationPath := "/api/v1/admin/feedback/" + key + "/moderation"
	c.call("POST", moderationPath, map[string]string{"decision": "CONFIRM_WITHDRAWAL"}, 409, "")
	var running int64
	if err := s.DB.Table("jobs").Where("kind='FEEDBACK_GITHUB' AND status='RUNNING' AND payload->>'feedbackId'=?", key).Count(&running).Error; err != nil || running != 1 {
		t.Fatalf("没有命中真实运行中投递: running=%d err=%v", running, err)
	}
	releaseOnce.Do(func() { close(release) })
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("释放合成响应后 Worker 未结束")
	}
	var row platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&row).Error; err != nil {
		t.Fatal(err)
	}
	if row.ModerationStatus != "WITHDRAWAL_REQUESTED" || row.GitHubIssueNumber != 93 || row.GitHubIssueURL != "https://github.com/synthetic/feedback/issues/93" || row.Description == "" || row.Contact == "" || row.Diagnostics == nil {
		t.Fatalf("远端成功收据未留给管理员清理，或错误提前擦除: %+v", row)
	}
	// 合成场景视为管理员已完成外部清理，再确认本地撤回并擦除敏感字段。
	confirmed := data[platform.FeedbackEntry](t, c.call("POST", moderationPath, map[string]string{"decision": "CONFIRM_WITHDRAWAL"}, 200, ""))
	if confirmed.ModerationStatus != "WITHDRAWN" || confirmed.Title != "" || confirmed.Description != "" || confirmed.Contact != "" || confirmed.Diagnostics != nil {
		t.Fatalf("外部清理完成后未确认并擦除内容: %+v", confirmed)
	}
	var persisted platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&persisted).Error; err != nil || persisted.ModerationStatus != "WITHDRAWN" || persisted.Description != "" || persisted.Contact != "" || persisted.Diagnostics != nil {
		t.Fatalf("确认撤回没有持久保存擦除结果: %+v err=%v", persisted, err)
	}
}
