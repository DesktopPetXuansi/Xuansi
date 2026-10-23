package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"
)

// 请求共用父行锁；相同发送并发落库只生成一条消息和一份额度。
func TestPostgresMessagesConcurrentRetryAndRoleIsolation(t *testing.T) {
	s, c, id, token := conversationFixture(t)
	key := uuid.NewString()
	input := map[string]string{"managementToken": token, "body": "并发补充"}
	raw, _ := json.Marshal(input)
	results := make(chan *httptest.ResponseRecorder, 8)
	for i := 0; i < 8; i++ {
		go func() {
			r := httptest.NewRequest("POST", "/api/v1/feedback/"+id+"/messages", bytes.NewReader(raw))
			r.Header.Set("Idempotency-Key", key)
			rc := chi.NewRouteContext()
			rc.URLParams.Add("id", id)
			r = r.WithContext(context.WithValue(r.Context(), chi.RouteCtxKey, rc))
			w := httptest.NewRecorder()
			s.sendUserFeedbackMessage(w, r)
			results <- w
		}()
	}
	var first []byte
	created := 0
	for i := 0; i < 8; i++ {
		w := <-results
		if w.Code == 201 {
			created++
		} else if w.Code != 200 {
			t.Fatalf("并发返回 %d %s", w.Code, w.Body.String())
		}
		if first == nil {
			first = w.Body.Bytes()
		} else if !bytes.Equal(first, w.Body.Bytes()) {
			t.Fatal("并发收据不一致")
		}
	}
	if created != 1 {
		t.Fatal("重复创建消息")
	}
	var total int64
	_ = s.DB.Table("feedback_submission_limits").Where("window_kind='MINUTE'").Select("coalesce(sum(submissions),0)").Scan(&total).Error
	if total != 2 {
		t.Fatalf("重放消耗多份额度: %d", total)
	}
	moderationAdmin(t, s, c)
	messageCall(t, c, "POST", "/api/v1/admin/feedback/"+id+"/messages", key, map[string]string{"body": "管理员独立角色"}, 201)
}

// 投递到本机协议服务器，确认公开内容只来源于初始反馈而无任何私有消息。
func TestPostgresMessagesNeverEnterGitHubDelivery(t *testing.T) {
	s, c, worker := setupFeedbackGitHub(t)
	s.Config.FeedbackGitHubRepository = "DesktopPetXuansi/Xuansi"
	s.Config.FeedbackGitHubToken = "synthetic-token"
	s.Config.FeedbackGitHubPublic = true
	worker.Config = s.Config
	id := uuid.NewString()
	feedbackCall(t, c, id, moderationInput("仅原问题公开", true), 201)
	token := strings.Repeat("a", 64)
	messageCall(t, c, "POST", "/api/v1/feedback/"+id+"/messages", uuid.NewString(), map[string]string{"managementToken": token, "body": "仅私信的机密合成标记"}, 201)
	approveFeedbackForDelivery(t, s, c, id)
	messageCall(t, c, "POST", "/api/v1/admin/feedback/"+id+"/messages", uuid.NewString(), map[string]string{"body": "开发者私信合成标记"}, 201)
	var posted string
	var postedMu sync.Mutex
	remote := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case r.URL.Path == "/repos/DesktopPetXuansi/Xuansi":
			fmt.Fprint(w, `{"private":false,"has_issues":true}`)
		case r.Method == "GET":
			fmt.Fprint(w, `[]`)
		case r.Method == "POST":
			b, _ := io.ReadAll(r.Body)
			postedMu.Lock()
			posted = string(b)
			postedMu.Unlock()
			w.WriteHeader(http.StatusCreated)
			fmt.Fprint(w, `{"number":43,"html_url":"https://github.com/DesktopPetXuansi/Xuansi/issues/43"}`)
		}
	}))
	defer remote.Close()
	target, _ := url.Parse(remote.URL)
	worker.FeedbackHTTPClient = &http.Client{Transport: feedbackGitHubTransport{target, http.DefaultTransport}, Timeout: 3 * time.Second}
	if e := worker.Tick(context.Background()); e != nil {
		t.Fatal(e)
	}
	postedMu.Lock()
	defer postedMu.Unlock()
	if posted == "" || !strings.Contains(posted, "仅原问题公开") || strings.Contains(posted, "私信") || strings.Contains(posted, token) || strings.Contains(posted, "example.test") {
		t.Fatalf("公开投递投影不安全: %s", posted)
	}
	var row feedbackEntry
	if e := s.DB.Where("id=?", id).First(&row).Error; e != nil || row.GitHubIssueNumber != 43 {
		t.Fatal("投递没有完成")
	}
	// 模拟已开始公开的反馈走真实撤回入口，首次请求就清除私信。
	c.call("POST", "/api/v1/feedback/"+id+"/withdrawal", map[string]string{"managementToken": token}, 200, "")
	var count int64
	_ = s.DB.Model(&feedbackMessage{}).Where("feedback_id=? AND body<>''", id).Count(&count).Error
	if count != 0 {
		t.Fatal("公开撤回首次请求仍保存私信")
	}
}
