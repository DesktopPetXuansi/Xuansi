package api

import (
	"bytes"
	"errors"
	"image"
	"image/png"
	"net/http"
	"net/http/httptest"
	"testing"

	"gorm.io/gorm"
	"xuansi/web/backend/internal/platform"
)

func smallPNG(t *testing.T) []byte {
	t.Helper()
	var out bytes.Buffer
	if e := png.Encode(&out, image.NewRGBA(image.Rect(0, 0, 4, 4))); e != nil {
		t.Fatal(e)
	}
	return out.Bytes()
}

// 管理员停用具有独立权限，原所有者不能通过工作台恢复下载。
func TestPostgresOwnerCannotUndoAdministratorDisable(t *testing.T) {
	s, owner, worker := setup(t)
	registered(t, s, owner, "disabled-owner@example.com")
	res := data[platform.Resource](t, owner.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "受管理资源"}, 201, ""))
	v := uploadReady(t, owner, worker, res, "1.0.0", "pet.png", smallPNG(t), "")
	ticket := data[struct{ URL string }](t, owner.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+v.Version.ID+"/download-authorizations", map[string]string{}, 200, ""))
	admin := &testClient{t: t, handler: owner.handler}
	admin.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	u := registered(t, s, admin, "administrator@example.com")
	if e := s.DB.Model(&platform.User{}).Where("id=?", u.ID).Update("role", "ADMIN").Error; e != nil {
		t.Fatal(e)
	}
	admin.call("PATCH", "/api/v1/admin/resources/"+res.ID, map[string]string{"status": "DISABLED"}, 204, "")
	for _, status := range []string{"ACTIVE", "HIDDEN"} {
		owner.call("PATCH", "/api/v1/resources/"+res.ID, map[string]string{"status": status}, 403, "")
	}
	owner.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+v.Version.ID+"/download-authorizations", map[string]string{}, 403, "")
	owner.call("GET", ticket.URL, nil, 404, "")
	admin.call("PATCH", "/api/v1/admin/resources/"+res.ID, map[string]string{"status": "ACTIVE"}, 204, "")
	owner.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+v.Version.ID+"/download-authorizations", map[string]string{}, 200, "")
}

// 数据库失败不是空资源库；只允许跳过确实不可访问的资源。
func TestPostgresLibraryReportsDatabaseFailure(t *testing.T) {
	s, c, _ := setup(t)
	registered(t, s, c, "library-error@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "资源库内容"}, 201, ""))
	c.call("PUT", "/api/v1/me/library/"+res.ID, map[string]string{}, 204, "")
	if e := s.DB.Callback().Query().Before("gorm:query").Register("test:resource-unavailable", func(db *gorm.DB) {
		if db.Statement.Table == "resources" {
			db.AddError(errors.New("测试数据库查询失败"))
		}
	}); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { s.DB.Callback().Query().Remove("test:resource-unavailable") })
	c.call("GET", "/api/v1/me/library", nil, 500, "")
}

func TestPostgresReadinessDistinguishesDatabaseOutage(t *testing.T) {
	s, c, _ := setup(t)
	c.call("GET", "/healthz", nil, 200, "")
	c.call("GET", "/readyz", nil, 200, "")
	sql, e := s.DB.DB()
	if e != nil {
		t.Fatal(e)
	}
	if e = sql.Close(); e != nil {
		t.Fatal(e)
	}
	c.call("GET", "/healthz", nil, 200, "")
	c.call("GET", "/readyz", nil, 500, "")
}

// 两个同时准备写入的浏览器操作，较早取得的CSRF令牌仍须有效。
func TestPostgresParallelCsrfPreparationDoesNotInvalidateWrite(t *testing.T) {
	s, c, _ := setup(t)
	registered(t, s, c, "parallel-csrf@example.com")
	c.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	previous := c.csrf
	c.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	r := httptest.NewRequest("PATCH", "/api/v1/me", bytes.NewBufferString(`{"displayName":"并行写入"}`))
	r.Header.Set("Origin", s.Config.AppURL)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("X-CSRF-Token", previous)
	r.AddCookie(&http.Cookie{Name: "xuansi_csrf", Value: c.csrf})
	r.AddCookie(&http.Cookie{Name: "xuansi_session", Value: c.session})
	w := httptest.NewRecorder()
	c.handler.ServeHTTP(w, r)
	if w.Code != 200 {
		t.Fatalf("并行准备写入导致CSRF失效：%d", w.Code)
	}
}
