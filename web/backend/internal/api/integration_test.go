package api

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"image"
	"image/png"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"strings"
	"testing"
	backend "xuansi/web/backend"
	"xuansi/web/backend/internal/oauth"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

type testClient struct {
	t             *testing.T
	handler       http.Handler
	csrf, session string
}

func (c *testClient) call(method, path string, input interface{}, expected int, bearer string) []byte {
	c.t.Helper()
	var b []byte
	var content string
	if raw, ok := input.([]byte); ok {
		b = raw
		content = "application/octet-stream"
	} else if form, ok := input.(url.Values); ok {
		b = []byte(form.Encode())
		content = "application/x-www-form-urlencoded"
	} else if input != nil {
		b, _ = json.Marshal(input)
		content = "application/json"
	}
	r := httptest.NewRequest(method, path, bytes.NewReader(b))
	r.Header.Set("Content-Type", content)
	r.Header.Set("Origin", "http://localhost:3000")
	r.Header.Set("X-CSRF-Token", c.csrf)
	r.Header.Set("Idempotency-Key", "integration-request-"+strings.ReplaceAll(path, "/", "-"))
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	if c.session != "" {
		r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: c.session})
	}
	if bearer != "" {
		r.Header.Set("Authorization", "Bearer "+bearer)
	}
	w := httptest.NewRecorder()
	c.handler.ServeHTTP(w, r)
	if w.Code != expected {
		c.t.Fatalf("%s %s: %d != %d: %s; location=%s", method, path, w.Code, expected, w.Body.String(), w.Header().Get("Location"))
	}
	for _, cookie := range w.Result().Cookies() {
		if cookie.Name == "xuansi_csrf" {
			c.csrf = cookie.Value
		}
		if cookie.Name == "xuansi_session" {
			c.session = cookie.Value
		}
	}
	return w.Body.Bytes()
}
func data[T interface{}](t *testing.T, b []byte) T {
	t.Helper()
	var out struct {
		Data T `json:"data"`
	}
	if e := json.Unmarshal(b, &out); e != nil {
		t.Fatal(e)
	}
	return out.Data
}
func setup(t *testing.T) (*Server, *testClient, *resource.Worker) {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("需要独立TEST_DATABASE_URL PostgreSQL")
	}
	if !strings.Contains(dsn, "xuansi_test") {
		t.Fatal("测试必须使用xuansi_test隔离库")
	}
	ctx := context.Background()
	db, e := platform.OpenDatabase(ctx, dsn)
	if e != nil {
		t.Fatal(e)
	}
	if e = platform.Migrate(ctx, db, backend.Migrations); e != nil {
		t.Fatal(e)
	}
	sql, _ := db.DB()
	t.Cleanup(func() { _ = sql.Close() })
	if e = db.Exec("TRUNCATE users,resources,client_releases,jobs CASCADE").Error; e != nil {
		t.Fatal(e)
	}
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	c := platform.Config{AppURL: "http://localhost:3000", Environment: "development", StorageDriver: "local", StoragePath: t.TempDir(), QuotaBytes: 1 << 28, MaxUploadBytes: 64 << 20, SMTPHost: "127.0.0.1", SMTPPort: "1025", SMTPFrom: "noreply@localhost", OAuthSecret: "integration-only-secret-at-least-32-chars"}
	storage := platform.LocalStorage{Root: c.StoragePath}
	s := &Server{DB: db, Config: c, Storage: storage, Log: log}
	s.OAuth = oauth.New(db, c, CurrentUser)
	client := &testClient{t: t, handler: s.Router()}
	client.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	worker := &resource.Worker{DB: db, Storage: storage, Config: c, Log: log, Owner: "test"}
	return s, client, worker
}
func registered(t *testing.T, s *Server, c *testClient, email string) platform.UserView {
	t.Helper()
	u := data[platform.UserView](t, c.call("POST", "/api/v1/auth/register", map[string]string{"email": email, "password": "test-strong-password-123", "displayName": "测试创作者"}, 201, ""))
	var job platform.Job
	if e := s.DB.Where("kind='MAIL'").Order("created_at DESC").First(&job).Error; e != nil {
		t.Fatal(e)
	}
	var mail struct{ Body string }
	_ = json.Unmarshal(job.Payload, &mail)
	uri := strings.TrimSpace(strings.Split(mail.Body, "\r\n")[1])
	parsed, _ := url.Parse(uri)
	c.call("POST", "/api/v1/auth/email-verifications/confirm", map[string]string{"token": parsed.Query().Get("token")}, 204, "")
	c.call("POST", "/api/v1/auth/email-verifications/confirm", map[string]string{"token": parsed.Query().Get("token")}, 400, "")
	c.call("POST", "/api/v1/auth/login", map[string]string{"email": email, "password": "wrong-password"}, 401, "")
	c.call("POST", "/api/v1/auth/login", map[string]string{"email": email, "password": "test-strong-password-123"}, 200, "")
	return u
}

// 真实PG覆盖注册、一次性验证、配额、Worker、私有隔离、下载与撤销。
func TestPostgresResourceFlow(t *testing.T) {
	s, c, w := setup(t)
	u := registered(t, s, c, "owner@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "测试图片", "author": "本人", "license": "CC0"}, 201, ""))
	var content bytes.Buffer
	if e := png.Encode(&content, image.NewRGBA(image.Rect(0, 0, 8, 8))); e != nil {
		t.Fatal(e)
	}
	type newVersion struct {
		Version platform.ResourceVersion `json:"version"`
		Upload  platform.Upload          `json:"upload"`
	}
	uploaded := data[newVersion](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]interface{}{"version": "1.0.0", "filename": "pet.png", "expectedBytes": content.Len()}, 201, ""))
	c.call("PUT", uploaded.Upload.URL, content.Bytes(), 204, "")
	c.call("POST", "/api/v1/uploads/"+uploaded.Upload.ID+"/completion", map[string]string{}, 202, "")
	c.call("POST", "/api/v1/uploads/"+uploaded.Upload.ID+"/completion", map[string]string{}, 202, "")
	for i := 0; i < 4; i++ {
		if e := w.Tick(context.Background()); e != nil {
			t.Fatal(e)
		}
	}
	upload := data[platform.Upload](t, c.call("GET", "/api/v1/uploads/"+uploaded.Upload.ID, nil, 200, ""))
	if upload.Status != "READY" {
		t.Fatalf("上传未就绪：%+v", upload)
	}
	manifest := data[resource.Manifest](t, c.call("GET", "/api/v1/resources/"+res.ID+"/versions/"+uploaded.Version.ID+"/manifest", nil, 200, ""))
	if manifest.Entrypoint != "pet.png" || len(manifest.Files) != 1 {
		t.Fatal("Manifest不正确")
	}
	anonymous := &testClient{t: t, handler: c.handler}
	anonymous.call("GET", "/api/v1/resources/"+res.ID, nil, 404, "")
	anonymous.call("GET", "/api/v1/resources/"+res.ID+"/versions/"+uploaded.Version.ID+"/manifest", nil, 404, "")
	c.call("PUT", "/api/v1/me/library/"+res.ID, map[string]interface{}{"pinnedVersionId": uploaded.Version.ID}, 204, "")
	ticket := data[struct {
		URL, SHA256 string
		Bytes       int64
	}](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+uploaded.Version.ID+"/download-authorizations", map[string]string{}, 200, ""))
	download, _ := url.Parse(ticket.URL)
	zipBytes := anonymous.call("GET", download.Path, nil, 200, "")
	hash := sha256.Sum256(zipBytes)
	if fmt.Sprintf("%x", hash) != ticket.SHA256 || int64(len(zipBytes)) != ticket.Bytes {
		t.Fatal("下载完整性不一致")
	}
	var fresh platform.User
	if e := s.DB.Where("id=?", u.ID).First(&fresh).Error; e != nil {
		t.Fatal(e)
	}
	if fresh.ReservedBytes != 0 || fresh.UsedBytes != ticket.Bytes {
		t.Fatalf("配额结算错误：%+v", fresh)
	}
	c.call("PATCH", "/api/v1/resources/"+res.ID, map[string]string{"status": "HIDDEN"}, 200, "")
	anonymous.call("GET", download.Path, nil, 404, "")
	c.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]interface{}{"version": "2.0.0", "filename": "pet.png", "expectedBytes": s.Config.QuotaBytes + 1}, 400, "")
}
func TestPostgresOAuthFlow(t *testing.T) {
	s, c, _ := setup(t)
	u := registered(t, s, c, "oauth@example.com")
	verifier := platform.RandomToken() + platform.RandomToken()
	hash := sha256.Sum256([]byte(verifier))
	params := url.Values{"response_type": {"code"}, "client_id": {"desktop-ai-pet"}, "redirect_uri": {"http://127.0.0.1:49351/oauth/callback"}, "scope": {"resources:read"}, "state": {"test-random-state"}, "code_challenge": {base64.RawURLEncoding.EncodeToString(hash[:])}, "code_challenge_method": {"S256"}, "consent": {"approve"}}
	redirect := data[struct {
		RedirectURL string `json:"redirectUrl"`
	}](t, c.call("POST", "/oauth/authorize", params, 200, ""))
	parsed, _ := url.Parse(redirect.RedirectURL)
	code := parsed.Query().Get("code")
	if code == "" || parsed.Query().Get("state") != "test-random-state" {
		t.Fatal("授权码或state缺失")
	}
	form := url.Values{"grant_type": {"authorization_code"}, "client_id": {"desktop-ai-pet"}, "redirect_uri": params["redirect_uri"], "code": {code}, "code_verifier": {verifier}}
	var tokens struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if e := json.Unmarshal(c.call("POST", "/oauth/token", form, 200, ""), &tokens); e != nil {
		t.Fatal(e)
	}
	if tokens.AccessToken == "" || tokens.RefreshToken == "" {
		t.Fatal("令牌缺失")
	}
	anonymous := &testClient{t: t, handler: c.handler}
	me := data[platform.UserView](t, anonymous.call("GET", "/api/v1/me", nil, 200, tokens.AccessToken))
	if me.ID != u.ID {
		t.Fatal("客户端身份错误")
	}
	for _, p := range []string{"/api/v1/me/sessions", "/api/v1/me/client-grants", "/api/v1/admin/users", "/api/v1/me/uploads"} {
		anonymous.call("GET", p, nil, 403, tokens.AccessToken)
	}
	for _, p := range []string{"/api/v1/me", "/api/v1/admin/users/" + u.ID} {
		anonymous.call("PATCH", p, map[string]string{"displayName": "越权"}, 403, tokens.AccessToken)
	}
	anonymous.call("PUT", "/api/v1/me/password", map[string]string{}, 403, tokens.AccessToken)
	anonymous.call("POST", "/api/v1/resources", map[string]string{}, 403, tokens.AccessToken)
	refresh := url.Values{"grant_type": {"refresh_token"}, "client_id": {"desktop-ai-pet"}, "refresh_token": {tokens.RefreshToken}}
	var rotated struct {
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	_ = json.Unmarshal(c.call("POST", "/oauth/token", refresh, 200, ""), &rotated)
	if rotated.RefreshToken == tokens.RefreshToken {
		t.Fatal("刷新未轮换")
	}
	anonymous.call("GET", "/api/v1/me", nil, 401, tokens.AccessToken)
	c.call("POST", "/oauth/token", refresh, 400, "")
	anonymous.call("GET", "/api/v1/me", nil, 401, rotated.AccessToken)
	var records []platform.OAuthRecord
	_ = s.DB.Find(&records).Error
	for _, record := range records {
		if strings.Contains(string(record.Payload), code) || strings.Contains(string(record.Payload), tokens.AccessToken) || strings.Contains(string(record.Payload), verifier) {
			t.Fatal("数据库保存了原始授权凭据")
		}
	}
}
