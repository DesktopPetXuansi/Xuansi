package platform

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
)

// 使用本机S3协议夹具验证SDK操作与签名字段，不冒充真实R2验收。
func TestS3StorageAdapter(t *testing.T) {
	var mu sync.Mutex
	objects := map[string][]byte{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if !strings.HasPrefix(r.Header.Get("Authorization"), "AWS4-HMAC-SHA256") {
			t.Error("请求缺少SigV4")
		}
		switch r.Method {
		case "PUT":
			b, e := io.ReadAll(r.Body)
			if e != nil {
				t.Error(e)
			}
			objects[r.URL.Path] = b
			w.WriteHeader(200)
		case "GET":
			b, ok := objects[r.URL.Path]
			if !ok {
				w.WriteHeader(404)
				return
			}
			w.Header().Set("Content-Type", "application/octet-stream")
			_, _ = w.Write(b)
		case "DELETE":
			delete(objects, r.URL.Path)
			w.WriteHeader(204)
		}
	}))
	defer server.Close()
	storage, e := NewStorage(context.Background(), Config{StorageDriver: "s3", S3Endpoint: server.URL, S3Region: "auto", S3Bucket: "test", S3AccessKey: "fixture-key", S3SecretKey: "fixture-secret"})
	if e != nil {
		t.Fatal(e)
	}
	ctx := context.Background()
	if e = storage.Put(ctx, "packages/example.zip", bytes.NewReader([]byte("test")), 4, "application/zip"); e != nil {
		t.Fatal(e)
	}
	body, e := storage.Open(ctx, "packages/example.zip")
	if e != nil {
		t.Fatal(e)
	}
	b, _ := io.ReadAll(body)
	_ = body.Close()
	if string(b) != "test" {
		t.Fatal("对象读写不一致")
	}
	signed, e := storage.PresignPut(ctx, "quarantine/upload.zip", 4)
	if e != nil {
		t.Fatal(e)
	}
	u, _ := url.Parse(signed)
	if u.Query().Get("X-Amz-Algorithm") != "AWS4-HMAC-SHA256" || u.Query().Get("X-Amz-Expires") != "900" {
		t.Fatal("预签名参数不正确")
	}
	if e = storage.Delete(ctx, "packages/example.zip"); e != nil {
		t.Fatal(e)
	}
}
func TestLocalStorageSizeAndTraversal(t *testing.T) {
	storage := LocalStorage{Root: t.TempDir()}
	ctx := context.Background()
	for _, key := range []string{"../escape", "a\\escape", "a:stream"} {
		if e := storage.Put(ctx, key, bytes.NewReader([]byte("x")), 1, ""); e == nil {
			t.Fatal("越界键被接受")
		}
	}
	if e := storage.Put(ctx, "quarantine/a", bytes.NewReader([]byte("12345")), 4, ""); e == nil {
		t.Fatal("超限写入被接受")
	}
	if _, e := storage.Open(ctx, "quarantine/a"); e == nil {
		t.Fatal("失败写入留下对象")
	}
}
