package api

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

type interceptedStorage struct {
	platform.ObjectStorage
	afterPut func(string)
}

// 在实际写入后、worker结算前注入取消操作，稳定重放异步竞态。
func (s interceptedStorage) Put(ctx context.Context, key string, body io.Reader, size int64, mime string) error {
	if e := s.ObjectStorage.Put(ctx, key, body, size, mime); e != nil {
		return e
	}
	if s.afterPut != nil {
		s.afterPut(key)
	}
	return nil
}

func pendingUpload(t *testing.T, c *testClient, res platform.Resource, purpose string, content []byte) platform.Upload {
	t.Helper()
	input := map[string]interface{}{"filename": "pet.png", "expectedBytes": len(content)}
	var upload platform.Upload
	if purpose == "COVER" {
		input["resourceId"], input["purpose"] = res.ID, purpose
		upload = data[platform.Upload](t, c.call("POST", "/api/v1/uploads", input, 201, ""))
	} else {
		input["version"] = "1.0.0"
		upload = data[createdVersion](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions", input, 201, "")).Upload
	}
	c.call("PUT", upload.URL, content, 204, "")
	c.call("POST", "/api/v1/uploads/"+upload.ID+"/completion", map[string]string{}, 202, "")
	return upload
}

func tickJobs(t *testing.T, w *resource.Worker) {
	t.Helper()
	for i := 0; i < 10; i++ {
		if e := w.Tick(context.Background()); e != nil {
			t.Fatal(e)
		}
	}
}

func collectObjects(t *testing.T, s *Server, w *resource.Worker) {
	t.Helper()
	// 测试只提前本隔离库的清理任务，不改变生产三分钟守护窗口。
	if e := s.DB.Model(&platform.Job{}).Where("kind='CLEANUP' AND status='QUEUED'").Update("run_at", time.Now().Add(-time.Second)).Error; e != nil {
		t.Fatal(e)
	}
	tickJobs(t, w)
}

func assertMissing(t *testing.T, root, key string) {
	t.Helper()
	if _, e := os.Stat(filepath.Join(root, filepath.FromSlash(key))); !os.IsNotExist(e) {
		t.Fatalf("未回收发布产物：%s，错误=%v", key, e)
	}
}

// 原文件可预留、规范ZIP超配额时，计费与对象回收必须一起收敛。
func TestPostgresNormalizedPackageQuotaCleanup(t *testing.T) {
	s, c, w := setup(t)
	u := registered(t, s, c, "normalized-quota@example.com")
	content := smallPNG(t)
	if e := s.DB.Model(&platform.User{}).Where("id=?", u.ID).Update("quota_bytes", len(content)+1).Error; e != nil {
		t.Fatal(e)
	}
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "配额边界"}, 201, ""))
	upload := pendingUpload(t, c, res, "VERSION", content)
	var key string
	w.Storage = interceptedStorage{ObjectStorage: s.Storage, afterPut: func(value string) {
		if strings.HasPrefix(value, "packages/") {
			key = value
		}
	}}
	tickJobs(t, w)
	state := data[platform.Upload](t, c.call("GET", "/api/v1/uploads/"+upload.ID, nil, 200, ""))
	if state.Status != "FAILED" || key == "" {
		t.Fatal("没有命中规范包超配额边界")
	}
	collectObjects(t, s, w)
	assertMissing(t, s.Config.StoragePath, key)
	var account platform.User
	if e := s.DB.First(&account, "id=?", u.ID).Error; e != nil || account.UsedBytes != 0 || account.ReservedBytes != 0 {
		t.Fatalf("失败后仍占配额：%v", e)
	}
}

func TestPostgresCancelledPackageCleanup(t *testing.T) {
	s, c, w := setup(t)
	registered(t, s, c, "cancel-package@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "取消校验"}, 201, ""))
	upload := pendingUpload(t, c, res, "VERSION", smallPNG(t))
	var key string
	w.Storage = interceptedStorage{ObjectStorage: s.Storage, afterPut: func(value string) {
		if strings.HasPrefix(value, "packages/") {
			key = value
			c.call("DELETE", "/api/v1/uploads/"+upload.ID, nil, 204, "")
		}
	}}
	tickJobs(t, w)
	state := data[platform.Upload](t, c.call("GET", "/api/v1/uploads/"+upload.ID, nil, 200, ""))
	if state.Status != "CANCELLED" || key == "" {
		t.Fatal("未重放结算前取消")
	}
	collectObjects(t, s, w)
	assertMissing(t, s.Config.StoragePath, key)
}

func TestPostgresCancelledIdenticalCoverPreservesExistingCover(t *testing.T) {
	s, c, w := setup(t)
	registered(t, s, c, "cancel-cover@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "封面竞态"}, 201, ""))
	content := smallPNG(t)
	pendingUpload(t, c, res, "COVER", content)
	tickJobs(t, w)
	if e := s.DB.First(&res, "id=?", res.ID).Error; e != nil || res.CoverKey == nil {
		t.Fatal("原封面未发布")
	}
	oldKey := *res.CoverKey
	upload := pendingUpload(t, c, res, "COVER", content)
	var newKey string
	w.Storage = interceptedStorage{ObjectStorage: s.Storage, afterPut: func(value string) {
		if strings.HasPrefix(value, "covers/") {
			newKey = value
			c.call("DELETE", "/api/v1/uploads/"+upload.ID, nil, 204, "")
		}
	}}
	tickJobs(t, w)
	collectObjects(t, s, w)
	if newKey == "" || newKey == oldKey {
		t.Fatal("封面上传未获得独立对象身份")
	}
	assertMissing(t, s.Config.StoragePath, newKey)
	c.call("GET", "/api/v1/resources/"+res.ID+"/cover", nil, 200, "")
	if e := s.DB.First(&res, "id=?", res.ID).Error; e != nil || *res.CoverKey != oldKey {
		t.Fatal("取消上传破坏了已发布封面引用")
	}
}
