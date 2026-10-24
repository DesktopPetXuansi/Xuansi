package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

// 本机协议服务器代替真实 GitHub，不创建公开 Issue，也不使用真实凭据。
type feedbackGitHubTransport struct {
	target *url.URL
	base   http.RoundTripper
}

func setupFeedbackGitHub(t *testing.T) (*Server, *testClient, *resource.Worker) {
	t.Helper()
	s, c, worker := setup(t)
	// 合成 Issue 编号会重复使用，必须同时清空收件和渠道，避免跨测试唯一键冲突。
	if err := s.DB.Exec("TRUNCATE feedback,feedback_github_channels CASCADE").Error; err != nil {
		t.Fatal(err)
	}
	return s, c, worker
}

// 投递测试也通过真实管理员接口审核；清除注册邮件，避免 Worker 先处理无关任务。
func approveFeedbackForDelivery(t *testing.T, s *Server, c *testClient, id string) {
	t.Helper()
	if c.session == "" {
		u := registered(t, s, c, "delivery-admin@example.test")
		if err := s.DB.Exec("UPDATE users SET role='ADMIN' WHERE id=?", u.ID).Error; err != nil {
			t.Fatal(err)
		}
		if err := s.DB.Exec("DELETE FROM jobs WHERE kind='MAIL'").Error; err != nil {
			t.Fatal(err)
		}
	}
	c.call("POST", "/api/v1/admin/feedback/"+id+"/moderation", map[string]string{"decision": "APPROVE"}, 200, "")
}

func (tr feedbackGitHubTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	copy := r.Clone(r.Context())
	copy.URL.Scheme, copy.URL.Host = tr.target.Scheme, tr.target.Host
	return tr.base.RoundTrip(copy)
}

func TestPostgresFeedbackGitHubAtomicQueueAndConsent(t *testing.T) {
	s, c, _ := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository = "DesktopPetXuansi/Xuansi"
	s.Config.FeedbackGitHubToken = "synthetic-token"
	s.Config.FeedbackGitHubPublic = true
	input := feedbackInput{Category: "BUG", Title: "合成公开问题", Description: "合成复现步骤", Contact: "private@example.test", PublicConsent: true}
	key := uuid.NewString()
	raw := feedbackCall(t, c, key, input, 201)
	feedbackCall(t, c, key, input, 200)
	moderationJobCount(t, s, 0)
	var pending platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&pending).Error; err != nil || pending.ModerationStatus != "PENDING" {
		t.Fatalf("创建没有进入待审核: %s %v", pending.ModerationStatus, err)
	}
	approveFeedbackForDelivery(t, s, c, key)
	approveFeedbackForDelivery(t, s, c, key)
	var jobs []platform.Job
	if err := s.DB.Where("kind='FEEDBACK_GITHUB'").Find(&jobs).Error; err != nil || len(jobs) != 1 {
		t.Fatalf("反馈重试没有复用唯一任务: jobs=%d err=%v", len(jobs), err)
	}
	if strings.Contains(string(jobs[0].Payload), input.Contact) || strings.Contains(string(raw), "github") {
		t.Fatal("任务正文或匿名收据泄露了私有字段")
	}
	var row platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&row).Error; err != nil || row.GitHubRepository != s.Config.FeedbackGitHubRepository || !row.GitHubPublic || !row.PublicConsent {
		t.Fatalf("没有冻结收件目的地与同意范围: %v", err)
	}
	// 旧客户端没有公开确认：仍然收件，绝不自动公开正文。
	input.PublicConsent = false
	input.Title = "合成未授权公开问题"
	privateKey := uuid.NewString()
	feedbackCall(t, c, privateKey, input, 201)
	c.call("POST", "/api/v1/admin/feedback/"+privateKey+"/moderation", map[string]string{"decision": "APPROVE"}, 409, "")
	var count int64
	s.DB.Model(&platform.Job{}).Where("kind='FEEDBACK_GITHUB'").Count(&count)
	if count != 1 {
		t.Fatal("未同意公开的旧客户端反馈进入了公开队列")
	}
}

func TestPostgresFeedbackGitHubQueueFailureRollsBackApproval(t *testing.T) {
	s, c, _ := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "owner/feedback", "synthetic-token"
	if err := s.DB.Exec("ALTER TABLE jobs ADD CONSTRAINT feedback_test_reject_job CHECK (kind <> 'FEEDBACK_GITHUB')").Error; err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { s.DB.Exec("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS feedback_test_reject_job") })
	key := uuid.NewString()
	input := feedbackInput{Category: "BUG", Title: "合成问题", Description: "队列失败测试", PublicConsent: true}
	first := data[feedbackReceipt](t, feedbackCall(t, c, key, input, 201))
	u := registered(t, s, c, "failed-approval-admin@example.test")
	if err := s.DB.Exec("UPDATE users SET role='ADMIN' WHERE id=?", u.ID).Error; err != nil {
		t.Fatal(err)
	}
	c.call("POST", "/api/v1/admin/feedback/"+key+"/moderation", map[string]string{"decision": "APPROVE"}, 500, "")
	var row platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&row).Error; err != nil || row.ModerationStatus != "PENDING" {
		t.Fatalf("队列失败没有回滚审核: %s %v", row.ModerationStatus, err)
	}
	moderationJobCount(t, s, 0)
	if retry := data[feedbackReceipt](t, feedbackCall(t, c, key, input, 200)); retry != first {
		t.Fatal("审核失败改变了原始收据")
	}
}

func TestPostgresFeedbackGitHubDeliveryRecoversUncertainResponse(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken, s.Config.FeedbackGitHubPublic = "DesktopPetXuansi/Xuansi", "synthetic-token", true
	worker.Config = s.Config
	var mu sync.Mutex
	var issueBody string
	posts := 0
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/repos/DesktopPetXuansi/Xuansi":
			fmt.Fprint(w, `{"private":false,"has_issues":true}`)
		case r.Method == "GET":
			if issueBody == "" {
				fmt.Fprint(w, `[]`)
			} else {
				json.NewEncoder(w).Encode([]map[string]interface{}{{"number": 42, "html_url": "https://github.com/DesktopPetXuansi/Xuansi/issues/42", "body": issueBody, "state": "closed"}})
			}
		case r.Method == "POST":
			posts++
			var input struct{ Body string }
			if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
				t.Error(err)
			}
			issueBody = input.Body
			// 远端已保存，但首次响应失败；重试应按稳定标记找到原 Issue。
			w.WriteHeader(503)
			fmt.Fprint(w, `{"message":"synthetic failure"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer remote.Close()
	target, _ := url.Parse(remote.URL)
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}, Timeout: 5 * time.Second}
	key := uuid.NewString()
	feedbackCall(t, c, key, feedbackInput{Category: "BUG", Title: "合成公开问题", Description: "合成步骤", Contact: "must-stay-private@example.test", PublicConsent: true}, 201)
	approveFeedbackForDelivery(t, s, c, key)
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	var job platform.Job
	s.DB.Where("kind='FEEDBACK_GITHUB'").First(&job)
	if job.Status != "QUEUED" || job.RunAt.Before(time.Now().Add(50*time.Second)) {
		t.Fatalf("不确定响应没有退避重试: status=%s runAt=%s", job.Status, job.RunAt)
	}
	s.DB.Model(&platform.Job{}).Where("id=?", job.ID).Update("run_at", time.Now().Add(-time.Second))
	// 同步推进持久化渠道时钟，模拟退避时间已经过去。
	s.DB.Exec("UPDATE feedback_github_channels SET not_before=now()-interval '1 second'")
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	s.DB.Where("id=?", job.ID).First(&job)
	var row platform.FeedbackEntry
	s.DB.Where("id=?", key).First(&row)
	mu.Lock()
	defer mu.Unlock()
	if posts != 1 || job.Status != "DONE" || row.GitHubIssueNumber != 42 || row.GitHubIssueURL != "https://github.com/DesktopPetXuansi/Xuansi/issues/42" {
		t.Fatalf("补偿查重失败: posts=%d job=%s attempts=%d error=%v issue=%d", posts, job.Status, job.Attempts, job.LastError, row.GitHubIssueNumber)
	}
	if strings.Contains(issueBody, "must-stay-private") || !strings.Contains(issueBody, key) {
		t.Fatal("公开正文越过了隐私边界或缺少稳定编号")
	}
	// 已完成任务被重新投递，也必须复用数据库已记录的 Issue。
	s.DB.Model(&platform.Job{}).Where("id=?", job.ID).Updates(map[string]interface{}{"status": "QUEUED", "run_at": time.Now().Add(-time.Second)})
	mu.Unlock()
	err := worker.Tick(context.Background())
	mu.Lock()
	if err != nil || posts != 1 {
		t.Fatal("已同步任务被重复创建")
	}
}

func TestPostgresFeedbackGitHubRateLimitAndDestinationFreeze(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "owner/feedback", "synthetic-token"
	worker.Config = s.Config
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "180")
		w.WriteHeader(429)
		io.WriteString(w, `{"message":"synthetic rate limit"}`)
	}))
	defer remote.Close()
	target, _ := url.Parse(remote.URL)
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}}
	key := uuid.NewString()
	feedbackCall(t, c, key, feedbackInput{Category: "OTHER", Title: "合成私有问题", Description: "频控测试", PublicConsent: true}, 201)
	approveFeedbackForDelivery(t, s, c, key)
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	var job platform.Job
	s.DB.Where("kind='FEEDBACK_GITHUB'").First(&job)
	if job.Status != "QUEUED" || job.RunAt.Before(time.Now().Add(170*time.Second)) {
		t.Fatal("没有遵守 GitHub Retry-After")
	}
	// 更换配置不能把已收集反馈偷偷发到另一个仓库。
	worker.Config.FeedbackGitHubRepository = "owner/another"
	s.DB.Model(&platform.Job{}).Where("id=?", job.ID).Update("run_at", time.Now().Add(-time.Second))
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	s.DB.Where("id=?", job.ID).First(&job)
	if job.Status != "FAILED" {
		t.Fatal("目的地变化后仍尝试转发历史反馈")
	}
}

// 私有仓库仍可能被其他协作者读取；未许可外送的反馈不能通过审核入队。
func TestPostgresFeedbackGitHubPrivateRepositoryRequiresConsent(t *testing.T) {
	s, c, _ := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "synthetic/private-feedback", "synthetic-token"
	s.Config.FeedbackGitHubPublic = false
	key := uuid.NewString()
	feedbackCall(t, c, key, feedbackInput{Category: "OTHER", Title: "仅向管理员反馈", Description: "没有同意向任何GitHub仓库发送"}, 201)
	moderationAdmin(t, s, c)
	c.call("POST", "/api/v1/admin/feedback/"+key+"/moderation", map[string]string{"decision": "APPROVE"}, 409, "")
	moderationJobCount(t, s, 0)
	var row platform.FeedbackEntry
	if err := s.DB.Where("id=?", key).First(&row).Error; err != nil || row.ModerationStatus != "PENDING" || row.GitHubRepository != "" {
		t.Fatalf("未许可反馈绑定了外送目的地或改变审核状态: %+v %v", row, err)
	}
}
