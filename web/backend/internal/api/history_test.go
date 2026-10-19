package api

import (
	"bytes"
	"encoding/json"
	"github.com/google/uuid"
	"image"
	"image/png"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"xuansi/web/backend/internal/history"
	"xuansi/web/backend/internal/platform"
)

func historyInput(at time.Time) map[string]interface{} {
	return map[string]interface{}{"kind": "APPEARANCE", "appearanceKind": "DEFAULT", "name": "默认形象",
		"occurredAt": at.UTC().Format(time.RFC3339Nano), "deviceLabel": "测试设备"}
}

// 使用真实隔离数据库，先锁定登录态、去重与严格输入边界。
func TestPostgresHistoryCRUD(t *testing.T) {
	s, c, _ := setup(t)
	registered(t, s, c, "history@example.com")
	id := uuid.NewString()
	input := map[string]interface{}{"kind": "APPEARANCE", "appearanceKind": "DEFAULT", "resourceId": nil, "resourceVersionId": nil, "name": "默认形象", "occurredAt": time.Now().UTC().Truncate(time.Microsecond).Format(time.RFC3339Nano), "deviceLabel": "测试设备"}
	c.call("PUT", "/api/v1/me/history/"+id, input, 204, "")
	c.call("PUT", "/api/v1/me/history/"+id, input, 204, "")
	input["name"] = "冲突"
	c.call("PUT", "/api/v1/me/history/"+id, input, 409, "")
	input["kind"] = "DOWNLOAD"
	c.call("PUT", "/api/v1/me/history/"+uuid.NewString(), input, 400, "")
	input["kind"] = "APPEARANCE"
	input["apiKey"] = "禁止入库"
	c.call("PUT", "/api/v1/me/history/"+uuid.NewString(), input, 400, "")
	c.call("GET", "/api/v1/me/history?cursor=bad", nil, 400, "")
	c.call("GET", "/api/v1/me/history?limit=101", nil, 400, "")
	c.call("DELETE", "/api/v1/me/history/"+id, nil, 204, "")
	c.call("DELETE", "/api/v1/me/history", nil, 204, "")
}

// 相同时间仍按 UUID 稳定分页；另一个账号既不能读取也不能清除原账号记录。
func TestPostgresHistoryIsolationAndPagination(t *testing.T) {
	s, first, _ := setup(t)
	registered(t, s, first, "history-first@example.com")
	at := time.Now().UTC().Truncate(time.Microsecond)
	for i := 0; i < 3; i++ {
		first.call("PUT", "/api/v1/me/history/"+uuid.NewString(), historyInput(at), 204, "")
	}
	var page struct {
		Data []history.Entry              `json:"data"`
		Meta struct{ NextCursor *string } `json:"meta"`
	}
	if e := json.Unmarshal(first.call("GET", "/api/v1/me/history?limit=2", nil, 200, ""), &page); e != nil {
		t.Fatal(e)
	}
	if len(page.Data) != 2 || page.Meta.NextCursor == nil {
		t.Fatal("首批历史或分页游标缺失")
	}
	seen := map[string]bool{page.Data[0].ID: true, page.Data[1].ID: true}
	cursor := *page.Meta.NextCursor
	if e := json.Unmarshal(first.call("GET", "/api/v1/me/history?limit=2&cursor="+cursor, nil, 200, ""), &page); e != nil {
		t.Fatal(e)
	}
	if len(page.Data) != 1 || page.Meta.NextCursor != nil || seen[page.Data[0].ID] {
		t.Fatal("历史分页重复或丢失")
	}
	second := &testClient{t: t, handler: s.Router()}
	second.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	registered(t, s, second, "history-second@example.com")
	if len(data[[]history.Entry](t, second.call("GET", "/api/v1/me/history", nil, 200, ""))) != 0 {
		t.Fatal("第二个账号读取到了其他用户的历史")
	}
	second.call("DELETE", "/api/v1/me/history/"+page.Data[0].ID, nil, 204, "")
	second.call("DELETE", "/api/v1/me/history", nil, 204, "")
	if len(data[[]history.Entry](t, first.call("GET", "/api/v1/me/history", nil, 200, ""))) != 3 {
		t.Fatal("第二个账号删除了其他用户的历史")
	}
	anonymous := &testClient{t: t, handler: s.Router()}
	anonymous.call("GET", "/api/v1/me/history", nil, 401, "")
}

func TestHistoryBearerScopesRemainSeparate(t *testing.T) {
	for _, scopes := range [][]string{{"resources:read"}, {"resources:read", "resources:write"}} {
		if bearerAllowed("GET", "/api/v1/me/history", scopes) || bearerAllowed("PUT", "/api/v1/me/history/"+uuid.NewString(), scopes) {
			t.Fatal("既有资源授权被隐式提升为历史授权")
		}
	}
	read := []string{"resources:read", "history:read"}
	if !bearerAllowed("GET", "/api/v1/me/history", read) || bearerAllowed("DELETE", "/api/v1/me/history", read) {
		t.Fatal("历史只读范围不正确")
	}
	write := append(read, "history:write")
	if !bearerAllowed("PUT", "/api/v1/me/history/"+uuid.NewString(), write) || !bearerAllowed("DELETE", "/api/v1/me/history", write) || bearerAllowed("POST", "/api/v1/resources", write) {
		t.Fatal("历史写入范围泄漏到资源上传")
	}
}

// 已有资源流同时锁定：申请票据不记录，完成传输去重，中断不计成功。
func TestPostgresDownloadHistoryCompletion(t *testing.T) {
	s, c, worker := setup(t)
	registered(t, s, c, "download-history@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "下载历史图片", "author": "本人", "license": "CC0"}, 201, ""))
	var content bytes.Buffer
	if e := png.Encode(&content, image.NewRGBA(image.Rect(0, 0, 8, 8))); e != nil {
		t.Fatal(e)
	}
	version := uploadReady(t, c, worker, res, "1.0.0", "history.png", content.Bytes(), "")
	requestTicket := func() string {
		response := data[struct{ URL string }](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions/"+version.Version.ID+"/download-authorizations", map[string]string{}, 200, ""))
		return response.URL[len(s.Config.AppURL):]
	}
	ticket := requestTicket()
	if len(data[[]history.Entry](t, c.call("GET", "/api/v1/me/history?kind=DOWNLOAD", nil, 200, ""))) != 0 {
		t.Fatal("仅申请票据就记录了下载成功")
	}
	c.call("GET", ticket, nil, 200, "")
	c.call("GET", ticket, nil, 200, "")
	if len(data[[]history.Entry](t, c.call("GET", "/api/v1/me/history?kind=DOWNLOAD", nil, 200, ""))) != 1 {
		t.Fatal("下载历史未去重")
	}
	interrupted := requestTicket()
	s.Router().ServeHTTP(&failedHistoryWriter{ResponseRecorder: httptest.NewRecorder()}, httptest.NewRequest(http.MethodGet, interrupted, nil))
	if len(data[[]history.Entry](t, c.call("GET", "/api/v1/me/history?kind=DOWNLOAD", nil, 200, ""))) != 1 {
		t.Fatal("中断传输被记录为下载成功")
	}
}

type failedHistoryWriter struct{ *httptest.ResponseRecorder }

func (w *failedHistoryWriter) Write(content []byte) (int, error) {
	return 0, io.ErrUnexpectedEOF
}
