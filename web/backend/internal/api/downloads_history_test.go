package api

import (
	"bytes"
	"context"
	"image"
	"image/png"
	"io"
	"testing"

	"xuansi/web/backend/internal/history"
	"xuansi/web/backend/internal/platform"
)

type shortDownloadStorage struct{ platform.ObjectStorage }

// 模拟存储对象被截短：读到 EOF 没有错误，但实际字节少于已发布包大小。
func (s shortDownloadStorage) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	body, err := s.ObjectStorage.Open(ctx, key)
	if err != nil {
		return nil, err
	}
	return &shortDownloadBody{Reader: io.LimitReader(body, 1), Closer: body}, nil
}

type shortDownloadBody struct {
	io.Reader
	io.Closer
}

func TestPostgresDownloadHistoryRejectsShortStorageRead(t *testing.T) {
	s, c, worker := setup(t)
	registered(t, s, c, "short-download-history@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "截短下载测试", "author": "本人", "license": "CC0"}, 201, ""))
	var content bytes.Buffer
	if err := png.Encode(&content, image.NewRGBA(image.Rect(0, 0, 8, 8))); err != nil {
		t.Fatal(err)
	}
	version := uploadReady(t, c, worker, res, "1.0.0", "short.png", content.Bytes(), "")
	ticket := data[struct{ URL string }](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+version.Version.ID+"/download-authorizations", map[string]string{}, 200, ""))
	fullStorage := s.Storage
	s.Storage = shortDownloadStorage{ObjectStorage: fullStorage}
	if body := c.call("GET", ticket.URL[len(s.Config.AppURL):], nil, 200, ""); len(body) != 1 {
		t.Fatalf("未注入存储短读：得到 %d 字节", len(body))
	}
	if len(data[[]history.Entry](t, c.call("GET", "/api/v1/me/history?kind=DOWNLOAD", nil, 200, ""))) != 0 {
		t.Fatal("存储正常 EOF 的截短响应被记录为下载成功")
	}
	// 同一票据在存储恢复后仍可完成，匿名访问公开资源也不会归入上传者历史。
	s.Storage = fullStorage
	c.call("GET", ticket.URL[len(s.Config.AppURL):], nil, 200, "")
	if err := s.DB.Model(&platform.Resource{}).Where("id=?", res.ID).Update("visibility", "PUBLIC").Error; err != nil {
		t.Fatal(err)
	}
	anonymous := &testClient{t: t, handler: s.Router()}
	anonymous.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	anonymousTicket := data[struct{ URL string }](t, anonymous.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+version.Version.ID+"/download-authorizations", map[string]string{}, 200, ""))
	anonymous.call("GET", anonymousTicket.URL[len(s.Config.AppURL):], nil, 200, "")
	if len(data[[]history.Entry](t, c.call("GET", "/api/v1/me/history?kind=DOWNLOAD", nil, 200, ""))) != 1 {
		t.Fatal("完整重试未记录，或匿名下载被错误记入账号历史")
	}
}
