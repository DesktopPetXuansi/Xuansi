package api

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/url"
	"strings"
	"testing"

	"xuansi/web/backend/internal/platform"
)

// 真正兑换过的客户端令牌和两个网站会话，都必须在密码恢复后失效。
func TestPostgresPasswordResetRevokesSessionsAndClientGrant(t *testing.T) {
	s, c, _ := setup(t)
	registered(t, s, c, "reset-owner@example.com")
	second := &testClient{t: t, handler: c.handler}
	second.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	second.call("POST", "/api/v1/auth/login", map[string]string{"email": "reset-owner@example.com", "password": "test-strong-password-123"}, 200, "")
	verifier := strings.Repeat("a", 64)
	hash := sha256.Sum256([]byte(verifier))
	form := url.Values{"client_id": {"desktop-ai-pet"}, "response_type": {"code"}, "scope": {"resources:read"}, "redirect_uri": {"http://127.0.0.1:49217/oauth/callback"}, "state": {"reset-test-state"}, "code_challenge": {base64.RawURLEncoding.EncodeToString(hash[:])}, "code_challenge_method": {"S256"}, "consent": {"approve"}}
	redirect := data[struct{ RedirectURL string }](t, c.call("POST", "/oauth/authorize", form, 200, ""))
	parsed, e := url.Parse(redirect.RedirectURL)
	if e != nil {
		t.Fatal(e)
	}
	var tokens struct {
		AccessToken string `json:"access_token"`
	}
	if e = json.Unmarshal(c.call("POST", "/oauth/token", url.Values{"client_id": {"desktop-ai-pet"}, "grant_type": {"authorization_code"}, "code": {parsed.Query().Get("code")}, "redirect_uri": {form.Get("redirect_uri")}, "code_verifier": {verifier}}, 200, ""), &tokens); e != nil {
		t.Fatal(e)
	}
	c.call("GET", "/api/v1/me/library", nil, 200, tokens.AccessToken)
	c.call("POST", "/api/v1/auth/password-resets", map[string]string{"email": "reset-owner@example.com"}, 202, "")
	var job platform.Job
	if e = s.DB.Where("kind='MAIL'").Order("created_at DESC").First(&job).Error; e != nil {
		t.Fatal(e)
	}
	var mail struct{ Body string }
	if e = json.Unmarshal(job.Payload, &mail); e != nil {
		t.Fatal(e)
	}
	link, e := url.Parse(strings.TrimSpace(strings.Split(mail.Body, "\r\n")[1]))
	if e != nil {
		t.Fatal(e)
	}
	reset := map[string]string{"token": link.Query().Get("token"), "password": "new-test-password-123"}
	c.call("POST", "/api/v1/auth/password-resets/confirm", reset, 204, "")
	c.call("GET", "/api/v1/me", nil, 401, "")
	second.call("GET", "/api/v1/me", nil, 401, "")
	c.call("GET", "/api/v1/me/library", nil, 401, tokens.AccessToken)
	c.call("POST", "/api/v1/auth/password-resets/confirm", reset, 400, "")
	c.call("POST", "/api/v1/auth/login", map[string]string{"email": "reset-owner@example.com", "password": "test-strong-password-123"}, 401, "")
	c.call("POST", "/api/v1/auth/login", map[string]string{"email": "reset-owner@example.com", "password": reset["password"]}, 200, "")
}
