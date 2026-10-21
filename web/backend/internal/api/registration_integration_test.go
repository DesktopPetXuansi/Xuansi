package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"xuansi/web/backend/internal/platform"
)

type registrationChallengeReply struct {
	ChallengeID string    `json:"challengeId"`
	ExpiresAt   time.Time `json:"expiresAt"`
	ResendAt    time.Time `json:"resendAt"`
}

// 使用独立 recorder：验收失败只报告状态，避免把验证码和密码写入测试日志。
func registrationRequest(t *testing.T, c *testClient, path string, input map[string]string, address string) *httptest.ResponseRecorder {
	t.Helper()
	body, err := json.Marshal(input)
	if err != nil {
		t.Fatal("无法编码注册请求")
	}
	r := httptest.NewRequest(http.MethodPost, "/api/v1/auth/"+path, bytes.NewReader(body))
	r.RemoteAddr = address
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", c.csrf)
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	w := httptest.NewRecorder()
	c.handler.ServeHTTP(w, r)
	return w
}

func registrationStatus(t *testing.T, w *httptest.ResponseRecorder, status int, code string) {
	t.Helper()
	if w.Code != status {
		t.Fatalf("注册接口状态=%d，预期=%d", w.Code, status)
	}
	if code != "" {
		var out struct {
			Error struct{ Code string } `json:"error"`
		}
		if json.Unmarshal(w.Body.Bytes(), &out) != nil || out.Error.Code != code {
			t.Fatalf("注册错误码不匹配，预期=%s", code)
		}
	}
}

func registrationCode(t *testing.T, s *Server, c *testClient, email string) (registrationChallengeReply, string) {
	t.Helper()
	w := registrationRequest(t, c, "registration-codes", map[string]string{"email": email}, "192.0.2.10:1234")
	registrationStatus(t, w, http.StatusAccepted, "")
	challenge := data[registrationChallengeReply](t, w.Body.Bytes())
	if uuid.Validate(challenge.ChallengeID) != nil || challenge.ExpiresAt.Before(time.Now().Add(9*time.Minute)) || challenge.ExpiresAt.After(time.Now().Add(11*time.Minute)) || challenge.ResendAt.Before(time.Now().Add(50*time.Second)) {
		t.Fatal("验证码挑战编号或有效时间不正确")
	}
	var job platform.Job
	if err := s.DB.Where("kind = 'MAIL' AND payload->>'registrationId' = ?", challenge.ChallengeID).First(&job).Error; err != nil {
		t.Fatal("验证码邮件未持久入队")
	}
	var mail struct{ To, Body string }
	if json.Unmarshal(job.Payload, &mail) != nil || mail.To != strings.ToLower(strings.TrimSpace(email)) {
		t.Fatal("验证码邮件收件地址未归一化")
	}
	code := regexp.MustCompile(`\b[0-9]{6}\b`).FindString(mail.Body)
	if len(code) != 6 {
		t.Fatal("邮件缺少六位 ASCII 验证码")
	}
	if strings.Contains(w.Body.String(), `"code":`) || strings.Contains(w.Body.String(), `"password":`) || strings.Contains(w.Body.String(), `"codeHash":`) {
		t.Fatal("验证码接口泄漏秘密字段")
	}
	for _, cookie := range w.Result().Cookies() {
		if cookie.Name == "xuansi_session" && cookie.Value != "" {
			t.Fatal("获取验证码不应创建会话")
		}
	}
	return challenge, code
}

func registrationInput(email string, challenge registrationChallengeReply, code string) map[string]string {
	return map[string]string{"email": email, "challengeId": challenge.ChallengeID, "code": code, "password": "registration-strong-password-123"}
}

func registrationCount(t *testing.T, s *Server, table string) int64 {
	t.Helper()
	var count int64
	if err := s.DB.Table(table).Count(&count).Error; err != nil {
		t.Fatal("无法读取注册验收数据表")
	}
	return count
}

func registrationAllowResend(t *testing.T, s *Server) {
	t.Helper()
	if err := s.DB.Exec("UPDATE registration_challenges SET resend_at = now() - interval '1 second'").Error; err != nil {
		t.Fatal("无法推进验证码重发时间")
	}
	if err := s.DB.Exec("UPDATE registration_send_limits SET next_send_at = now() - interval '1 second'").Error; err != nil {
		t.Fatal("无法推进共享邮件重发时间")
	}
}

// 真实 PostgreSQL 验证邮箱证明、用户与会话在一次事务内完成，取码阶段不创建账号。
func TestPostgresRegistrationSinglePage(t *testing.T) {
	s, c, _ := setup(t)
	challenge, code := registrationCode(t, s, c, "  New.Member@Example.com  ")
	if registrationCount(t, s, "users") != 0 || registrationCount(t, s, "web_sessions") != 0 {
		t.Fatal("取码时创建了用户或会话")
	}
	var stored struct{ CodeHash, EmailHash string }
	if err := s.DB.Table("registration_challenges").Where("id = ?", challenge.ChallengeID).Take(&stored).Error; err != nil {
		t.Fatal("验证码挑战未保存")
	}
	if len(stored.CodeHash) != 64 || len(stored.EmailHash) != 64 {
		t.Fatal("挑战未使用独立摘要保存验证码和邮箱")
	}
	w := registrationRequest(t, c, "registrations", registrationInput("NEW.MEMBER@example.com", challenge, code), "192.0.2.10:1234")
	registrationStatus(t, w, http.StatusCreated, "")
	user := data[platform.UserView](t, w.Body.Bytes())
	if !user.EmailVerified || user.Role != "USER" || user.Status != "ACTIVE" || user.DisplayName != "新朋友" || user.Email != "new.member@example.com" {
		t.Fatal("注册结果不是默认昵称的已验证普通用户")
	}
	for _, cookie := range w.Result().Cookies() {
		if cookie.Name == "xuansi_session" {
			if !cookie.HttpOnly || cookie.SameSite != http.SameSiteLaxMode {
				t.Fatal("注册会话 Cookie 缺少保护属性")
			}
			c.session = cookie.Value
		}
	}
	if c.session == "" || registrationCount(t, s, "web_sessions") != 1 {
		t.Fatal("注册成功未创建唯一会话")
	}
	me := data[platform.UserView](t, c.call("GET", "/api/v1/me", nil, 200, ""))
	if me.ID != user.ID {
		t.Fatal("注册后的会话身份不一致")
	}
	w = registrationRequest(t, c, "registrations", registrationInput(user.Email, challenge, code), "192.0.2.10:1234")
	registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
	if registrationCount(t, s, "users") != 1 || registrationCount(t, s, "web_sessions") != 1 {
		t.Fatal("消费过的验证码又创建了账号或会话")
	}
}

func TestPostgresRegistrationInvalidProof(t *testing.T) {
	for _, scenario := range []string{"wrong-email", "wrong-id", "malformed-id", "expired", "malformed-code", "wrong-code"} {
		t.Run(scenario, func(t *testing.T) {
			s, c, _ := setup(t)
			challenge, code := registrationCode(t, s, c, "proof@example.com")
			input := registrationInput("proof@example.com", challenge, code)
			switch scenario {
			case "wrong-email":
				input["email"] = "another@example.com"
			case "wrong-id":
				input["challengeId"] = uuid.NewString()
			case "malformed-id":
				input["challengeId"] = "invalid-registration-id"
			case "expired":
				if err := s.DB.Exec("UPDATE registration_challenges SET expires_at = now() - interval '1 second'").Error; err != nil {
					t.Fatal("无法模拟过期")
				}
			case "malformed-code":
				input["code"] = "１２３４５６"
			case "wrong-code":
				input["code"] = wrongRegistrationCode(code)
			}
			w := registrationRequest(t, c, "registrations", input, "192.0.2.10:1234")
			registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
			if registrationCount(t, s, "users") != 0 || registrationCount(t, s, "web_sessions") != 0 {
				t.Fatal("无效邮箱证明创建了账号或会话")
			}
		})
	}
}

func wrongRegistrationCode(code string) string {
	if code == "000000" {
		return "000001"
	}
	return "000000"
}

func TestPostgresRegistrationWrongAttemptsPersist(t *testing.T) {
	s, c, _ := setup(t)
	challenge, code := registrationCode(t, s, c, "attempts@example.com")
	for i := 0; i < 5; i++ {
		w := registrationRequest(t, c, "registrations", registrationInput("attempts@example.com", challenge, wrongRegistrationCode(code)), "192.0.2.10:1234")
		registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
	}
	var attempts int
	if err := s.DB.Table("registration_challenges").Select("attempts").Where("id = ?", challenge.ChallengeID).Scan(&attempts).Error; err != nil || attempts != 5 {
		t.Fatal("五次错误尝试未持久记录")
	}
	// 重建 Router 清除进程内限流器，锁定仍须由数据库生效。
	c.handler = s.Router()
	w := registrationRequest(t, c, "registrations", registrationInput("attempts@example.com", challenge, code), "192.0.2.10:1234")
	registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
	if registrationCount(t, s, "users") != 0 {
		t.Fatal("达到错误次数上限后仍可注册")
	}
}

func TestPostgresRegistrationResendInvalidatesPrevious(t *testing.T) {
	s, c, _ := setup(t)
	old, oldCode := registrationCode(t, s, c, "resend@example.com")
	w := registrationRequest(t, c, "registration-codes", map[string]string{"email": "RESEND@example.com"}, "192.0.2.10:1234")
	registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
	if w.Header().Get("Retry-After") == "" || registrationCount(t, s, "jobs") != 1 {
		t.Fatal("重发冷却未提供重试时间或重复发信")
	}
	registrationAllowResend(t, s)
	fresh, code := registrationCode(t, s, c, "resend@example.com")
	if old.ChallengeID == fresh.ChallengeID || registrationCount(t, s, "registration_challenges") != 1 {
		t.Fatal("重发没有替换同邮箱的旧挑战")
	}
	w = registrationRequest(t, c, "registrations", registrationInput("resend@example.com", old, oldCode), "192.0.2.10:1234")
	registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
	w = registrationRequest(t, c, "registrations", registrationInput("resend@example.com", fresh, code), "192.0.2.10:1234")
	registrationStatus(t, w, 201, "")
}

func TestPostgresRegistrationConcurrentConsumption(t *testing.T) {
	s, c, _ := setup(t)
	challenge, code := registrationCode(t, s, c, "concurrent@example.com")
	var wg sync.WaitGroup
	results := make(chan int, 6)
	for i := 0; i < 6; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- registrationRequest(t, c, "registrations", registrationInput("concurrent@example.com", challenge, code), "192.0.2.10:1234").Code
		}()
	}
	wg.Wait()
	close(results)
	created := 0
	for status := range results {
		if status == 201 {
			created++
		} else if status != 400 {
			t.Fatalf("并发消费返回非预期状态=%d", status)
		}
	}
	if created != 1 || registrationCount(t, s, "users") != 1 || registrationCount(t, s, "web_sessions") != 1 {
		t.Fatal("同一验证码并发消费没有保证唯一账号与会话")
	}
}

func TestPostgresRegistrationCannotReplaceExistingAccount(t *testing.T) {
	for _, verified := range []bool{false, true} {
		t.Run(fmt.Sprintf("verified-%t", verified), func(t *testing.T) {
			s, c, _ := setup(t)
			challenge, code := registrationCode(t, s, c, "existing@example.com")
			hash, err := platform.HashPassword("existing-password-123")
			if err != nil {
				t.Fatal("无法创建合成密码摘要")
			}
			u := platform.User{ID: uuid.NewString(), Email: "existing@example.com", PasswordHash: hash, DisplayName: "已有用户", Role: "ADMIN", Status: "ACTIVE", EmailVerified: verified, QuotaBytes: s.Config.QuotaBytes, CreatedAt: time.Now(), UpdatedAt: time.Now()}
			if err := s.DB.Create(&u).Error; err != nil {
				t.Fatal("无法创建合成已有账号")
			}
			w := registrationRequest(t, c, "registrations", registrationInput(u.Email, challenge, wrongRegistrationCode(code)), "192.0.2.10:1234")
			registrationStatus(t, w, 400, "REGISTRATION_CODE_INVALID")
			w = registrationRequest(t, c, "registrations", registrationInput(u.Email, challenge, code), "192.0.2.10:1234")
			registrationStatus(t, w, 409, "EMAIL_ALREADY_REGISTERED")
			var unchanged platform.User
			if err := s.DB.Where("id = ?", u.ID).First(&unchanged).Error; err != nil || unchanged.PasswordHash != hash || unchanged.Role != "ADMIN" || unchanged.EmailVerified != verified || unchanged.DisplayName != u.DisplayName {
				t.Fatal("注册接口篡改了已有账号")
			}
			if registrationCount(t, s, "web_sessions") != 0 {
				t.Fatal("注册接口登录了已有账号")
			}
		})
	}
}

func TestPostgresRegistrationPersistentSendLimits(t *testing.T) {
	t.Run("normalized-email-hour", func(t *testing.T) {
		s, c, _ := setup(t)
		for i := 0; i < 5; i++ {
			registrationAllowResend(t, s)
			registrationCode(t, s, c, "  Limits@Example.com ")
		}
		registrationAllowResend(t, s)
		c.handler = s.Router()
		w := registrationRequest(t, c, "registration-codes", map[string]string{"email": "limits@example.com"}, "192.0.2.11:1234")
		registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
		if w.Header().Get("Retry-After") == "" || registrationCount(t, s, "jobs") != 5 {
			t.Fatal("邮箱小时额度没有跨 Router 持久生效")
		}
	})
	t.Run("ip-hour", func(t *testing.T) {
		s, c, _ := setup(t)
		for i := 0; i < 20; i++ {
			w := registrationRequest(t, c, "registration-codes", map[string]string{"email": fmt.Sprintf("ip-limit-%d@example.com", i)}, "192.0.2.20:1234")
			registrationStatus(t, w, 202, "")
		}
		c.handler = s.Router()
		w := registrationRequest(t, c, "registration-codes", map[string]string{"email": "ip-limit-over@example.com"}, "192.0.2.20:4567")
		registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
		if w.Header().Get("Retry-After") == "" || registrationCount(t, s, "jobs") != 20 {
			t.Fatal("IP 小时额度未持久生效")
		}
	})
}

// 注入队列写入失败，证明限额、挑战和邮件入队同事务回滚。
func TestPostgresRegistrationQueueFailureRollsBack(t *testing.T) {
	s, c, _ := setup(t)
	if err := s.DB.Exec(`CREATE FUNCTION registration_test_reject_mail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic queue unavailable'; END $$`).Error; err != nil {
		t.Fatal("无法安装合成队列故障")
	}
	t.Cleanup(func() {
		_ = s.DB.Exec("DROP TRIGGER IF EXISTS registration_test_reject_mail ON jobs").Error
		_ = s.DB.Exec("DROP FUNCTION IF EXISTS registration_test_reject_mail()").Error
	})
	if err := s.DB.Exec("CREATE TRIGGER registration_test_reject_mail BEFORE INSERT ON jobs FOR EACH ROW EXECUTE FUNCTION registration_test_reject_mail()").Error; err != nil {
		t.Fatal("无法启用合成队列故障")
	}
	w := registrationRequest(t, c, "registration-codes", map[string]string{"email": "rollback@example.com"}, "192.0.2.10:1234")
	registrationStatus(t, w, 500, "")
	if registrationCount(t, s, "registration_send_limits") != 0 || registrationCount(t, s, "registration_challenges") != 0 || registrationCount(t, s, "jobs") != 0 {
		t.Fatal("邮件入队失败仍消耗额度或留下挑战")
	}
	if err := s.DB.Exec("DROP TRIGGER registration_test_reject_mail ON jobs").Error; err != nil {
		t.Fatal("无法恢复合成队列")
	}
	registrationCode(t, s, c, "rollback@example.com")
}

func TestPostgresRegistrationLegacyMailSharesLimits(t *testing.T) {
	t.Run("legacy-register-and-verify-count-towards-codes", func(t *testing.T) {
		s, c, _ := setup(t)
		w := registrationRequest(t, c, "register", map[string]string{"email": "shared@example.com", "password": "legacy-strong-password-123", "displayName": "合成旧用户"}, "192.0.2.10:1234")
		registrationStatus(t, w, 201, "")
		for i := 0; i < 4; i++ {
			registrationAllowResend(t, s)
			w = registrationRequest(t, c, "email-verifications", map[string]string{"email": "SHARED@example.com"}, "192.0.2.10:1234")
			registrationStatus(t, w, 202, "")
		}
		registrationAllowResend(t, s)
		c.handler = s.Router()
		w = registrationRequest(t, c, "registration-codes", map[string]string{"email": "shared@example.com"}, "192.0.2.11:1234")
		registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
		if registrationCount(t, s, "jobs") != 5 {
			t.Fatal("旧注册/重发验证没有共用邮件小时额度")
		}
	})
	t.Run("codes-block-legacy-register", func(t *testing.T) {
		s, c, _ := setup(t)
		for i := 0; i < 5; i++ {
			registrationAllowResend(t, s)
			registrationCode(t, s, c, "legacy-blocked@example.com")
		}
		registrationAllowResend(t, s)
		w := registrationRequest(t, c, "register", map[string]string{"email": "LEGACY-BLOCKED@example.com", "password": "legacy-strong-password-123", "displayName": "合成旧用户"}, "192.0.2.10:1234")
		registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
		if registrationCount(t, s, "users") != 0 || registrationCount(t, s, "jobs") != 5 {
			t.Fatal("旧注册绕过额度或留下不可用账号")
		}
	})
}

// 无 SMTP 端口可用：失效邮件仍完成且擦除 payload，证明在联网之前跳过。
func TestPostgresRegistrationWorkerSkipsStaleMail(t *testing.T) {
	for _, scenario := range []string{"expired", "replaced", "consumed"} {
		t.Run(scenario, func(t *testing.T) {
			s, c, worker := setup(t)
			worker.Config.SMTPPort = "0"
			challenge, code := registrationCode(t, s, c, "worker@example.com")
			var job platform.Job
			if err := s.DB.Where("kind='MAIL'").First(&job).Error; err != nil {
				t.Fatal("缺少合成邮件任务")
			}
			switch scenario {
			case "expired":
				if err := s.DB.Exec("UPDATE registration_challenges SET expires_at = now() - interval '1 second'").Error; err != nil {
					t.Fatal("无法模拟验证码过期")
				}
			case "replaced":
				registrationAllowResend(t, s)
				registrationCode(t, s, c, "worker@example.com")
			case "consumed":
				w := registrationRequest(t, c, "registrations", registrationInput("worker@example.com", challenge, code), "192.0.2.10:1234")
				registrationStatus(t, w, 201, "")
			}
			if err := worker.Tick(context.Background()); err != nil {
				t.Fatal("处理失效验证码邮件失败")
			}
			if err := s.DB.Where("id = ?", job.ID).First(&job).Error; err != nil || job.Status != "DONE" || string(job.Payload) != "{}" {
				t.Fatal("失效验证码邮件尝试了 SMTP 或未擦除秘密载荷")
			}
		})
	}
}

func TestPostgresRegistrationAcceptsLeadingZeroCode(t *testing.T) {
	s, c, _ := setup(t)
	challenge, _ := registrationCode(t, s, c, "zero@example.com")
	// 固定合成挑战，不依赖随机生成恰好命中前导零，覆盖验证码字符串语义。
	if err := s.DB.Table("registration_challenges").Where("id = ?", challenge.ChallengeID).Update("code_hash", s.registrationDigest("code", challenge.ChallengeID, "zero@example.com", "000123")).Error; err != nil {
		t.Fatal("无法设置合成前导零验证码")
	}
	w := registrationRequest(t, c, "registrations", registrationInput("zero@example.com", challenge, "000123"), "192.0.2.10:1234")
	registrationStatus(t, w, 201, "")
}

func TestPostgresRegistrationSessionFailureRollsBack(t *testing.T) {
	s, c, _ := setup(t)
	challenge, code := registrationCode(t, s, c, "session-rollback@example.com")
	if err := s.DB.Exec(`CREATE FUNCTION registration_test_reject_session() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic session unavailable'; END $$`).Error; err != nil {
		t.Fatal("无法安装合成会话故障")
	}
	t.Cleanup(func() {
		_ = s.DB.Exec("DROP TRIGGER IF EXISTS registration_test_reject_session ON web_sessions").Error
		_ = s.DB.Exec("DROP FUNCTION IF EXISTS registration_test_reject_session()").Error
	})
	if err := s.DB.Exec("CREATE TRIGGER registration_test_reject_session BEFORE INSERT ON web_sessions FOR EACH ROW EXECUTE FUNCTION registration_test_reject_session()").Error; err != nil {
		t.Fatal("无法启用合成会话故障")
	}
	w := registrationRequest(t, c, "registrations", registrationInput("session-rollback@example.com", challenge, code), "192.0.2.10:1234")
	registrationStatus(t, w, 500, "")
	var consumed int64
	if err := s.DB.Table("registration_challenges").Where("id = ? AND consumed_at IS NOT NULL", challenge.ChallengeID).Count(&consumed).Error; err != nil {
		t.Fatal("无法检查验证码消费状态")
	}
	if consumed != 0 || registrationCount(t, s, "users") != 0 || registrationCount(t, s, "web_sessions") != 0 {
		t.Fatal("会话写入失败未回滚用户和验证码消费")
	}
	if err := s.DB.Exec("DROP TRIGGER registration_test_reject_session ON web_sessions").Error; err != nil {
		t.Fatal("无法恢复合成会话创建")
	}
	w = registrationRequest(t, c, "registrations", registrationInput("session-rollback@example.com", challenge, code), "192.0.2.10:1234")
	registrationStatus(t, w, 201, "")
}

// 验证邮件重发的冷却行为不能暴露邮箱是否存在或是否停用。
func TestPostgresRegistrationLegacyVerificationDoesNotEnumerate(t *testing.T) {
	for index, scenario := range []string{"ACTIVE", "MISSING", "DISABLED"} {
		t.Run(scenario, func(t *testing.T) {
			s, c, _ := setup(t)
			email := strings.ToLower(scenario) + "-verification@example.com"
			address := fmt.Sprintf("192.0.2.%d:1234", 60+index)
			if scenario != "MISSING" {
				hash, err := platform.HashPassword("synthetic-verification-password-123")
				if err != nil {
					t.Fatal("无法创建合成密码摘要")
				}
				user := platform.User{ID: uuid.NewString(), Email: email, PasswordHash: hash, DisplayName: "验证重发验收", Role: "USER", Status: scenario, QuotaBytes: s.Config.QuotaBytes, CreatedAt: time.Now(), UpdatedAt: time.Now()}
				if err := s.DB.Create(&user).Error; err != nil {
					t.Fatal("无法创建合成验证用户")
				}
			}
			// 用本场景独立来源建立新注册与旧验证接口共享的邮箱冷却。
			w := registrationRequest(t, c, "registration-codes", map[string]string{"email": email}, address)
			registrationStatus(t, w, 202, "")
			if registrationCount(t, s, "jobs") != 1 {
				t.Fatal("初始验证码没有唯一入队")
			}
			w = registrationRequest(t, c, "email-verifications", map[string]string{"email": strings.ToUpper(email)}, address)
			registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
			if w.Header().Get("Retry-After") == "" || registrationCount(t, s, "jobs") != 1 {
				t.Fatal("共享冷却响应缺少重试时间或意外投递邮件")
			}
			registrationAllowResend(t, s)
			w = registrationRequest(t, c, "email-verifications", map[string]string{"email": email}, address)
			registrationStatus(t, w, 202, "")
			wantedJobs := int64(1)
			if scenario == "ACTIVE" {
				wantedJobs = 2
			}
			if registrationCount(t, s, "jobs") != wantedJobs || registrationCount(t, s, "web_sessions") != 0 {
				t.Fatal("旧验证向不存在/停用账号发信，或意外创建会话")
			}
			var sends int
			if err := s.DB.Table("registration_send_limits").Select("sends").Where("scope = 'EMAIL'").Scan(&sends).Error; err != nil || sends != 2 {
				t.Fatal("各账号状态没有同样消耗邮箱发送额度")
			}
			// 通过请求后也应进入同样冷却，不能依据后续重试辨认空邮箱。
			w = registrationRequest(t, c, "email-verifications", map[string]string{"email": email}, address)
			registrationStatus(t, w, 429, "REGISTRATION_RATE_LIMITED")
		})
	}
}
