package api

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"net/url"
	"strings"
	"testing"
	"xuansi/web/backend/internal/platform"
)

type clientUploadTokens struct {
	Access  string `json:"access_token"`
	Refresh string `json:"refresh_token"`
	Scope   string `json:"scope"`
}

func clientUploadGrant(t *testing.T, c *testClient, scope string) clientUploadTokens {
	t.Helper()
	verifier := platform.RandomToken() + platform.RandomToken()
	hash := sha256.Sum256([]byte(verifier))
	form := url.Values{"response_type": {"code"}, "client_id": {"desktop-ai-pet"}, "redirect_uri": {"http://127.0.0.1:49351/oauth/callback"}, "scope": {scope}, "state": {"upload-random-state"}, "code_challenge": {base64.RawURLEncoding.EncodeToString(hash[:])}, "code_challenge_method": {"S256"}, "consent": {"approve"}}
	redirect := data[struct {
		RedirectURL string `json:"redirectUrl"`
	}](t, c.call("POST", "/oauth/authorize", form, 200, ""))
	u, _ := url.Parse(redirect.RedirectURL)
	var tokens clientUploadTokens
	if e := json.Unmarshal(c.call("POST", "/oauth/token", url.Values{"grant_type": {"authorization_code"}, "client_id": {"desktop-ai-pet"}, "redirect_uri": form["redirect_uri"], "code": {u.Query().Get("code")}, "code_verifier": {verifier}}, 200, ""), &tokens); e != nil {
		t.Fatal(e)
	}
	return tokens
}

// 真正走 Fosite 与 PG 上传链，客户端只有 Bearer，没有 Cookie 或 CSRF。
func TestPostgresClientUpload(t *testing.T) {
	s, c, w := setup(t)
	owner := registered(t, s, c, "upload-owner@example.com")
	read := clientUploadGrant(t, c, "resources:read")
	write := clientUploadGrant(t, c, "resources:read resources:write")
	if !strings.Contains(write.Scope, "resources:write") {
		t.Fatal("未授予写权限")
	}
	native := &testClient{t: t, handler: c.handler}
	native.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "只读越权"}, 403, read.Access)
	// 只读令牌即使同时携带有效网站 Cookie，也不能回退使用网站身份。
	c.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "只读越权"}, 403, read.Access)
	res := data[platform.Resource](t, native.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "客户端模型", "author": "本人"}, 201, write.Access))
	content := modelFixture(t)
	v := data[createdVersion](t, native.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]interface{}{"version": "1.0.0", "filename": "model.zip", "entrypoint": "model.model3.json", "expectedBytes": len(content)}, 201, write.Access))
	native.call("PUT", v.Upload.URL, content, 204, write.Access)
	native.call("POST", "/api/v1/uploads/"+v.Upload.ID+"/completion", map[string]string{}, 202, write.Access)
	native.call("POST", "/api/v1/uploads/"+v.Upload.ID+"/completion", map[string]string{}, 202, write.Access)
	for n := 0; n < 8; n++ {
		if e := w.Tick(context.Background()); e != nil {
			t.Fatal(e)
		}
	}
	if upload := data[platform.Upload](t, native.call("GET", "/api/v1/uploads/"+v.Upload.ID, nil, 200, write.Access)); upload.Status != "READY" {
		t.Fatalf("上传未就绪: %s", upload.Status)
	}
	native.call("PATCH", "/api/v1/resources/"+res.ID, map[string]string{"currentVersionId": v.Version.ID}, 200, write.Access)
	native.call("PUT", "/api/v1/me/library/"+res.ID, map[string]string{"pinnedVersionId": v.Version.ID}, 204, write.Access)
	for _, field := range []string{"name", "description", "author", "license", "source", "status", "tags", "visibility"} {
		native.call("PATCH", "/api/v1/resources/"+res.ID, map[string]interface{}{field: nil, "currentVersionId": v.Version.ID}, 403, write.Access)
	}
	for _, p := range []string{"/api/v1/me", "/api/v1/admin/users/" + owner.ID} {
		native.call("PATCH", p, map[string]string{"displayName": "越权"}, 403, write.Access)
	}
	native.call("PUT", "/api/v1/me/password", map[string]string{}, 403, write.Access)
	native.call("DELETE", "/api/v1/resources/"+res.ID, nil, 403, write.Access)
	native.call("POST", "/api/v1/uploads", map[string]string{}, 403, write.Access)
	other := &testClient{t: t, handler: c.handler}
	other.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	registered(t, s, other, "upload-other@example.com")
	otherWrite := clientUploadGrant(t, other, "resources:read resources:write")
	native.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]string{}, 404, otherWrite.Access)
	native.call("PATCH", "/api/v1/resources/"+res.ID, map[string]string{"currentVersionId": v.Version.ID}, 404, otherWrite.Access)
	native.call("GET", "/api/v1/uploads/"+v.Upload.ID, nil, 404, otherWrite.Access)
	native.call("PUT", v.Upload.URL, content, 404, otherWrite.Access)
	native.call("POST", "/api/v1/uploads/"+v.Upload.ID+"/completion", map[string]string{}, 404, otherWrite.Access)
	native.call("DELETE", "/api/v1/uploads/"+v.Upload.ID, nil, 404, otherWrite.Access)
	native.call("PUT", "/api/v1/me/library/"+res.ID, map[string]string{"pinnedVersionId": v.Version.ID}, 404, otherWrite.Access)
	native.call("GET", "/api/v1/uploads/"+v.Upload.ID, nil, 403, read.Access)
	// 取消尚未上传的版本释放配额，但客户端不能删除资源本身。
	cancelled := data[createdVersion](t, native.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]interface{}{"version": "2.0.0", "filename": "model.zip", "entrypoint": "model.model3.json", "expectedBytes": len(content)}, 201, write.Access))
	native.call("DELETE", "/api/v1/uploads/"+cancelled.Upload.ID, nil, 204, write.Access)
	var fresh platform.User
	if e := s.DB.Where("id=?", owner.ID).First(&fresh).Error; e != nil {
		t.Fatal(e)
	}
	if fresh.ReservedBytes != 0 {
		t.Fatal("取消未释放预留配额")
	}
	// 管理员本人也仅得到模型上传能力。
	if e := s.DB.Model(&platform.User{}).Where("id=?", owner.ID).Update("role", "ADMIN").Error; e != nil {
		t.Fatal(e)
	}
	native.call("GET", "/api/v1/admin/users", nil, 403, write.Access)
	native.call("PATCH", "/api/v1/resources/"+res.ID, map[string]string{"status": "HIDDEN"}, 403, write.Access)
	var rotated clientUploadTokens
	if e := json.Unmarshal(native.call("POST", "/oauth/token", url.Values{"grant_type": {"refresh_token"}, "client_id": {"desktop-ai-pet"}, "refresh_token": {write.Refresh}}, 200, ""), &rotated); e != nil {
		t.Fatal(e)
	}
	if !strings.Contains(rotated.Scope, "resources:write") {
		t.Fatal("刷新丢失上传权限")
	}
	native.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "刷新上传"}, 201, rotated.Access)
	native.call("GET", "/api/v1/me", nil, 401, write.Access)
	native.call("POST", "/oauth/revoke", url.Values{"client_id": {"desktop-ai-pet"}, "token": {rotated.Refresh}, "token_type_hint": {"refresh_token"}}, 200, "")
	native.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "已撤销"}, 401, rotated.Access)
}

func TestPostgresClientUploadRejectsInvalidScopes(t *testing.T) {
	s, c, _ := setup(t)
	registered(t, s, c, "scope-owner@example.com")
	for _, scope := range []string{"resources:write", "resources:read resources:read", "resources:read resources:write resources:write", "resources:read admin", ""} {
		c.call("POST", "/oauth/authorize", url.Values{"response_type": {"code"}, "client_id": {"desktop-ai-pet"}, "redirect_uri": {"http://127.0.0.1:49351/oauth/callback"}, "scope": {scope}, "state": {"upload-random-state"}, "code_challenge": {"validchallenge"}, "code_challenge_method": {"S256"}, "consent": {"approve"}}, 400, "")
	}
}

// 未声明的网站子路径不能因资源 URL 前缀而获得客户端权限。
func TestClientUploadRouteBoundary(t *testing.T) {
	const id = "00000000-0000-4000-8000-000000000001"
	for _, test := range []struct{ method, path string }{
		{"GET", "/api/v1/resources/" + id + "/audit"},
		{"GET", "/api/v1/client/releases/private"},
		{"POST", "/api/v1/resources/" + id + "/bogus/download-authorizations"},
		{"POST", "/api/v1/resources/" + id + "/publish"},
		{"PATCH", "/api/v1/resources/" + id + "/versions"},
		{"DELETE", "/api/v1/me/library/" + id},
		{"PUT", "/api/v1/uploads/" + id + "/completion"},
	} {
		if bearerAllowed(test.method, test.path, []string{"resources:read", "resources:write"}) {
			t.Errorf("未声明路由被允许: %s %s", test.method, test.path)
		}
	}
}
