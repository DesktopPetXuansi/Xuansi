package api

import (
	"encoding/json"
	"fmt"
	"net/url"
	"testing"
	"time"
	"xuansi/web/backend/internal/platform"
)

type adminUsersTestPage struct {
	Data []platform.UserView
	Meta struct {
		NextCursor *string
		Total      int64
	}
}

func readAdminUsersPage(t *testing.T, c *testClient, query string) adminUsersTestPage {
	t.Helper()
	raw := c.call("GET", "/api/v1/admin/users"+query, nil, 200, "")
	var page adminUsersTestPage
	if err := json.Unmarshal(raw, &page); err != nil {
		t.Fatal(err)
	}
	return page
}

// 直接播种只用于列表查询边界；网站登录和权限继续通过真实注册流程建立。
func seedAdminUsers(t *testing.T, s *Server, count int) []platform.User {
	t.Helper()
	at := time.Now().UTC().Add(-time.Hour).Truncate(time.Microsecond)
	rows := make([]platform.User, count)
	for index := range rows {
		rows[index] = platform.User{
			ID:    fmt.Sprintf("70000000-0000-4000-8000-%012d", index+1),
			Email: fmt.Sprintf("list-%02d@example.test", index+1), PasswordHash: "synthetic-unusable-password",
			DisplayName: fmt.Sprintf("列表用户%02d", index+1), Role: "USER", Status: "ACTIVE",
			EmailVerified: index%2 == 0, QuotaBytes: 1 << 20, CreatedAt: at, UpdatedAt: at,
		}
	}
	if err := s.DB.Create(&rows).Error; err != nil {
		t.Fatal(err)
	}
	return rows
}

// 超过默认20人后仍能访问所有原账号；相同创建时间以ID稳定排序，新注册不挤乱后续页。
func TestPostgresAdminUsersStablePagination(t *testing.T) {
	s, admin, _ := setup(t)
	moderationAdmin(t, s, admin)
	seeded := seedAdminUsers(t, s, 27)
	first := readAdminUsersPage(t, admin, "")
	if len(first.Data) != 20 || first.Meta.Total != 28 || first.Meta.NextCursor == nil {
		t.Fatalf("首屏未提供完整分页：本页=%d，总数=%d，有下一页=%v", len(first.Data), first.Meta.Total, first.Meta.NextCursor != nil)
	}
	seen := map[string]bool{}
	for _, user := range first.Data {
		seen[user.ID] = true
	}
	for index := 1; index < len(first.Data); index++ {
		if first.Data[index].ID != seeded[len(seeded)-index].ID {
			t.Fatal("相同创建时间的账号没有按ID稳定排序")
		}
	}
	newcomer := platform.User{
		ID: "80000000-0000-4000-8000-000000000001", Email: "newcomer@example.test",
		PasswordHash: "synthetic-unusable-password", DisplayName: "分页后新注册", Role: "USER", Status: "ACTIVE",
		QuotaBytes: 1 << 20, CreatedAt: time.Now().UTC().Add(time.Minute), UpdatedAt: time.Now().UTC(),
	}
	if err := s.DB.Create(&newcomer).Error; err != nil {
		t.Fatal(err)
	}
	second := readAdminUsersPage(t, admin, "?cursor="+url.QueryEscape(*first.Meta.NextCursor))
	if len(second.Data) != 8 || second.Meta.Total != 29 || second.Meta.NextCursor != nil {
		t.Fatal("第二页遗漏账号、总数受游标影响或错误地生成了第三页")
	}
	for _, user := range second.Data {
		if seen[user.ID] || user.ID == newcomer.ID {
			t.Fatal("新账号导致已有分页重复或不稳定")
		}
		seen[user.ID] = true
	}
	if len(seen) != 28 {
		t.Fatal("未能遍历分页开始时的所有账号")
	}
	all := readAdminUsersPage(t, admin, "?limit=100")
	if len(all.Data) != 29 || all.Meta.NextCursor != nil {
		t.Fatal("合法分页大小没有生效")
	}
	// data仍是UserView数组，旧调用方可继续忽略新增的meta。
	raw := admin.call("GET", "/api/v1/admin/users?limit=1", nil, 200, "")
	if len(data[[]platform.UserView](t, raw)) != 1 {
		t.Fatal("旧data数组响应不兼容")
	}
}
