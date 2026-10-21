package api

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

// 两个实际并发 worker 也只能有一个进入 GitHub，网络等待期间不持有 SQL 事务。
func TestPostgresFeedbackGitHubChannelSerializesWorkers(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "concurrent/feedback", "synthetic-token"
	worker.Config = s.Config
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	var calls atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			close(entered)
		}
		select {
		case <-release:
		case <-r.Context().Done():
			return
		}
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer func() {
		once.Do(func() { close(release) })
		remote.Close()
	}()
	target, _ := url.Parse(remote.URL)
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}}
	other := &resource.Worker{DB: s.DB, Config: s.Config, Log: s.Log, Owner: "concurrent-worker", FeedbackHTTPClient: worker.FeedbackHTTPClient}
	for i := 0; i < 2; i++ {
		feedbackCall(t, c, uuid.NewString(), feedbackInput{Category: "OTHER", Title: "合成问题", Description: "跨进程串行"}, 201)
	}
	done := make(chan error, 1)
	go func() { done <- worker.Tick(context.Background()) }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("首个 worker 没有开始请求")
	}
	if err := other.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	if calls.Load() != 1 {
		t.Fatalf("独占租约未串行化远端请求: %d", calls.Load())
	}
	once.Do(func() { close(release) })
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	var jobs []platform.Job
	s.DB.Where("kind='FEEDBACK_GITHUB'").Order("created_at").Find(&jobs)
	if len(jobs) != 2 || jobs[0].Attempts != 1 || jobs[1].Attempts != 0 {
		t.Fatalf("并发空等消耗了投递次数: %+v", jobs)
	}
}

// 限流属于共享渠道，另一个进程不能靠领取另一条任务绕过冷却。
func TestPostgresFeedbackGitHubSharedChannelCooldown(t *testing.T) {
	for _, status := range []int{http.StatusTooManyRequests, http.StatusForbidden} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			s, c, worker := setupFeedbackGitHub(t)
			s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "cooldown/"+uuid.NewString(), "synthetic-token"
			worker.Config = s.Config
			var calls atomic.Int32
			remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if status == http.StatusTooManyRequests {
					w.Header().Set("Retry-After", "180")
				} else {
					w.Header().Set("X-RateLimit-Remaining", "0")
					w.Header().Set("X-RateLimit-Reset", fmt.Sprint(time.Now().Add(180*time.Second).Unix()))
				}
				w.WriteHeader(status)
			}))
			defer remote.Close()
			target, _ := url.Parse(remote.URL)
			worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}}
			other := &resource.Worker{DB: s.DB, Config: s.Config, Log: s.Log, Owner: "other-worker", FeedbackHTTPClient: worker.FeedbackHTTPClient}
			for i := 0; i < 2; i++ {
				feedbackCall(t, c, uuid.NewString(), feedbackInput{Category: "OTHER", Title: "合成问题", Description: "共享限流测试"}, 201)
			}
			if err := worker.Tick(context.Background()); err != nil {
				t.Fatal(err)
			}
			if err := other.Tick(context.Background()); err != nil {
				t.Fatal(err)
			}
			if calls.Load() != 1 {
				t.Fatalf("另一 worker 绕过共享限流: calls=%d", calls.Load())
			}
			var jobs []platform.Job
			if err := s.DB.Where("kind='FEEDBACK_GITHUB'").Order("created_at").Find(&jobs).Error; err != nil {
				t.Fatal(err)
			}
			if len(jobs) != 2 || jobs[0].Attempts != 1 || jobs[1].Attempts != 0 || jobs[1].Status != "QUEUED" || jobs[1].RunAt.Before(time.Now().Add(170*time.Second)) {
				t.Fatalf("等待渠道消耗次数或没有延期: %+v", jobs)
			}
			// 即便调度器重复唤醒，空等也不会烧掉投递预算。
			for i := 0; i < 11; i++ {
				s.DB.Model(&platform.Job{}).Where("id=?", jobs[1].ID).Update("run_at", time.Now().Add(-time.Second))
				if err := other.Tick(context.Background()); err != nil {
					t.Fatal(err)
				}
			}
			var waiting platform.Job
			s.DB.Where("id=?", jobs[1].ID).First(&waiting)
			if waiting.Attempts != 0 || waiting.Status != "QUEUED" || calls.Load() != 1 {
				t.Fatalf("空等耗尽投递次数: %+v calls=%d", waiting, calls.Load())
			}
			// 推进数据库时钟后，这条此前未出网的任务可以继续。
			s.DB.Exec("UPDATE feedback_github_channels SET not_before=now()-interval '1 second'")
			s.DB.Model(&platform.Job{}).Where("id=?", waiting.ID).Update("run_at", time.Now().Add(-time.Second))
			if err := other.Tick(context.Background()); err != nil {
				t.Fatal(err)
			}
			s.DB.Where("id=?", waiting.ID).First(&waiting)
			if calls.Load() != 2 || waiting.Attempts != 1 {
				t.Fatalf("冷却结束没有继续实际投递: attempts=%d calls=%d", waiting.Attempts, calls.Load())
			}
		})
	}
}

func TestPostgresFeedbackGitHubChannelLeaseRecovery(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubToken = "lease/feedback", "synthetic-token"
	worker.Config = s.Config
	var calls atomic.Int32
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/repos/lease/feedback":
			fmt.Fprint(w, `{"private":true,"has_issues":true}`)
		case r.Method == "GET":
			fmt.Fprint(w, `[]`)
		default:
			w.WriteHeader(201)
			fmt.Fprint(w, `{"number":77,"html_url":"https://github.com/lease/feedback/issues/77"}`)
		}
	}))
	defer remote.Close()
	target, _ := url.Parse(remote.URL)
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}}
	feedbackCall(t, c, uuid.NewString(), feedbackInput{Category: "OTHER", Title: "合成问题", Description: "租约恢复"}, 201)
	if err := s.DB.Exec("INSERT INTO feedback_github_channels(repository,not_before,lease_owner,lease_until) VALUES (?,now()-interval '1 second',?,now()+interval '3 minutes')", s.Config.FeedbackGitHubRepository, uuid.NewString()).Error; err != nil {
		t.Fatal(err)
	}
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	var job platform.Job
	s.DB.Where("kind='FEEDBACK_GITHUB'").First(&job)
	if calls.Load() != 0 || job.Attempts != 0 || job.Status != "QUEUED" {
		t.Fatalf("租约占用时仍出网或计数: %+v calls=%d", job, calls.Load())
	}
	// 模拟进程崩溃后短租约过期，无需人工清除 owner。
	s.DB.Exec("UPDATE feedback_github_channels SET lease_until=now()-interval '1 second'")
	s.DB.Model(&platform.Job{}).Where("id=?", job.ID).Update("run_at", time.Now().Add(-time.Second))
	if err := worker.Tick(context.Background()); err != nil {
		t.Fatal(err)
	}
	s.DB.Where("id=?", job.ID).First(&job)
	if calls.Load() != 3 || job.Attempts != 1 || job.Status != "DONE" {
		t.Fatalf("租约到期没有恢复: %+v calls=%d", job, calls.Load())
	}
	var channel struct {
		NotBefore  time.Time
		LeaseOwner *string
	}
	s.DB.Table("feedback_github_channels").First(&channel)
	if channel.LeaseOwner != nil || channel.NotBefore.Before(time.Now().Add(500*time.Millisecond)) {
		t.Fatal("成功后没有释放租约或保留最小间隔")
	}
}
