package api

import (
	"encoding/json"
	"fmt"
	"net/url"
	"testing"
	"time"
	"xuansi/web/backend/internal/platform"
)

// 一整页配套动作排在形象之前，证明分类必须在数据库分页前完成。
func TestPostgresResourceGroupsBeforePagination(t *testing.T) {
	s, client, _ := setup(t)
	owner := registered(t, s, client, "resource-groups@example.test")
	rows := make([]platform.Resource, 0, 31)
	for index := 1; index <= 31; index++ {
		kind := "MOTION"
		switch index {
		case 26:
			kind = "MODEL"
		case 27:
			kind = "IMAGE"
		case 28:
			kind = "ANIMATION"
		case 29:
			kind = "EXPRESSION"
		}
		row := platform.Resource{ID: fmt.Sprintf("60000000-0000-4000-8000-%012d", index), OwnerID: owner.ID, Kind: kind,
			Name: fmt.Sprintf("分组样本%02d", index), Tags: json.RawMessage("[]"), Visibility: "PUBLIC", Status: "ACTIVE", CreatedAt: time.Now().UTC(), UpdatedAt: time.Now().UTC()}
		if index == 30 {
			row.Kind, row.Visibility = "MODEL", "PRIVATE"
		}
		if index == 31 {
			row.Kind, row.Status = "IMAGE", "DISABLED"
		}
		rows = append(rows, row)
	}
	if err := s.DB.Create(&rows).Error; err != nil {
		t.Fatal(err)
	}
	public := &testClient{t: t, handler: s.Router()}
	appearances := data[[]platform.Resource](t, public.call("GET", "/api/v1/resources?group=APPEARANCE", nil, 200, ""))
	if len(appearances) != 3 || appearances[0].Kind != "MODEL" || appearances[1].Kind != "IMAGE" || appearances[2].Kind != "ANIMATION" {
		t.Fatal("形象合集未在公开可见性和分页前正确筛选")
	}
	filtered := data[[]platform.Resource](t, public.call("GET", "/api/v1/resources?group=APPEARANCE&kind=IMAGE", nil, 200, ""))
	if len(filtered) != 1 || filtered[0].Kind != "IMAGE" {
		t.Fatal("组与原kind筛选没有取交集")
	}
	// 缺省仍为旧的全资源范围；不能改变客户端或个人管理的既有请求。
	all := data[[]platform.Resource](t, public.call("GET", "/api/v1/resources?limit=100", nil, 200, ""))
	if len(all) != 29 {
		t.Fatal("未传group时的公开资源范围发生变化")
	}
	personal := data[[]platform.Resource](t, client.call("GET", "/api/v1/me/resources?limit=100", nil, 200, ""))
	if len(personal) != 31 {
		t.Fatal("个人资源默认不应套用公开形象分组")
	}
	seen := map[string]bool{}
	cursor := ""
	for {
		var page struct {
			Data []platform.Resource
			Meta struct{ NextCursor string }
		}
		raw := public.call("GET", "/api/v1/resources?group=ADDON&limit=7&cursor="+url.QueryEscape(cursor), nil, 200, "")
		if err := json.Unmarshal(raw, &page); err != nil {
			t.Fatal(err)
		}
		for _, row := range page.Data {
			if seen[row.ID] || (row.Kind != "MOTION" && row.Kind != "EXPRESSION") {
				t.Fatal("配套资源分页重复或混入独立形象")
			}
			seen[row.ID] = true
		}
		if page.Meta.NextCursor == "" {
			break
		}
		cursor = page.Meta.NextCursor
	}
	if len(seen) != 26 {
		t.Fatal("配套资源没有完整跨页读取")
	}
	public.call("GET", "/api/v1/resources?group=UNKNOWN", nil, 400, "")
}
