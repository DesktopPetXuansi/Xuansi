package api

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"xuansi/web/backend/internal/platform"
)

// 版本详情允许按身份查询已发布测试渠道，草稿和不匹配的平台不能泄露。
func TestPostgresPublishedReleaseDetailAndPlatformFilters(t *testing.T) {
	s, c, _ := setup(t)
	stamp := time.Now()
	stable := platform.ClientRelease{ID: uuid.NewString(), Version: "1.0.0", Channel: "STABLE", SourceCommit: "test", PublishedAt: &stamp}
	beta := platform.ClientRelease{ID: uuid.NewString(), Version: "1.1.0", Channel: "BETA", SourceCommit: "test", PublishedAt: &stamp}
	draft := platform.ClientRelease{ID: uuid.NewString(), Version: "1.2.0", Channel: "BETA", SourceCommit: "test"}
	for _, row := range []*platform.ClientRelease{&stable, &beta, &draft} {
		if e := s.DB.Create(row).Error; e != nil {
			t.Fatal(e)
		}
		artifact := platform.ReleaseArtifact{ID: uuid.NewString(), ReleaseID: row.ID, OS: "windows", Arch: "x64", DistributionType: "ONLINE_INSTALLER", DownloadURL: "https://example.invalid/setup.exe", SHA256: strings.Repeat("a", 64), Bytes: 1, SystemRequirements: json.RawMessage(`[]`)}
		if e := s.DB.Create(&artifact).Error; e != nil {
			t.Fatal(e)
		}
	}
	rows := data[[]platform.ClientRelease](t, c.call("GET", "/api/v1/client/releases", nil, 200, ""))
	if len(rows) != 1 || rows[0].ID != stable.ID || len(rows[0].Artifacts) != 1 {
		t.Fatalf("公开列表未按稳定渠道加载安装包：%+v", rows)
	}
	view := data[platform.ClientRelease](t, c.call("GET", "/api/v1/client/releases/"+beta.ID+"?os=windows&arch=x64", nil, 200, ""))
	if view.ID != beta.ID || len(view.Artifacts) != 1 {
		t.Fatal("已发布版本详情缺少匹配安装包")
	}
	c.call("GET", "/api/v1/client/releases/"+draft.ID, nil, 404, "")
	c.call("GET", "/api/v1/client/releases/"+beta.ID+"?channel=STABLE", nil, 404, "")
	c.call("GET", "/api/v1/client/releases/"+beta.ID+"?arch=arm64", nil, 404, "")
	c.call("GET", "/api/v1/client/releases/latest?os=linux", nil, 404, "")
	c.call("GET", "/api/v1/client/releases/not-a-uuid", nil, 400, "")
}
