package api

import (
	"bytes"
	"net/url"
	"strings"
	"testing"
)

// 搜索先作用于全体账号，再分页；特殊字符按字面查找，不能扩大为SQL通配搜索。
func TestPostgresAdminUsersGlobalSearchAndFilters(t *testing.T) {
	s, admin, _ := setup(t)
	moderationAdmin(t, s, admin)
	rows := seedAdminUsers(t, s, 27)
	changes := []struct {
		Name, Email, Role, Status string
	}{
		{"老页目标", "older-target@example.test", "USER", "ACTIVE"},
		{"百分%昵称", "percent@example.test", "USER", "ACTIVE"},
		{"下划_昵称", "underscore@example.test", "USER", "ACTIVE"},
		{"路径\\昵称", "slash@example.test", "USER", "ACTIVE"},
		{"停用管理员", "disabled-admin@example.test", "ADMIN", "DISABLED"},
		{"停用普通用户", "disabled-user@example.test", "USER", "DISABLED"},
	}
	for index, change := range changes {
		if err := s.DB.Model(&rows[index]).Updates(map[string]interface{}{
			"display_name": change.Name, "email": change.Email, "role": change.Role, "status": change.Status,
		}).Error; err != nil {
			t.Fatal(err)
		}
	}
	for _, keyword := range []string{"OLDER-TARGET", "老页目标", "%", "_", "\\"} {
		page := readAdminUsersPage(t, admin, "?search="+url.QueryEscape(keyword))
		if page.Meta.Total != 1 || len(page.Data) != 1 || page.Meta.NextCursor != nil {
			t.Fatalf("关键词%q未全局、按字面匹配", keyword)
		}
	}
	filtered := readAdminUsersPage(t, admin, "?role=ADMIN&status=DISABLED")
	if filtered.Meta.Total != 1 || len(filtered.Data) != 1 || filtered.Data[0].ID != rows[4].ID {
		t.Fatal("角色和状态筛选未同时生效")
	}
	first := readAdminUsersPage(t, admin, "?search=列表用户&limit=2")
	if len(first.Data) != 2 || first.Meta.Total != 21 || first.Meta.NextCursor == nil {
		t.Fatal("筛选后的总数与分页错误")
	}
	second := readAdminUsersPage(t, admin, "?search=列表用户&limit=2&cursor="+url.QueryEscape(*first.Meta.NextCursor))
	if len(second.Data) != 2 || second.Meta.Total != 21 || second.Data[0].ID == first.Data[0].ID {
		t.Fatal("筛选后的下一页错误")
	}
	empty := readAdminUsersPage(t, admin, "?search=不存在的昵称")
	if empty.Data == nil || len(empty.Data) != 0 || empty.Meta.Total != 0 || empty.Meta.NextCursor != nil {
		t.Fatal("空搜索结果必须保留空数组与零总数")
	}
	raw := admin.call("GET", "/api/v1/admin/users?limit=100", nil, 200, "")
	for _, forbidden := range []string{"passwordHash", "password_hash", "synthetic-unusable-password"} {
		if bytes.Contains(raw, []byte(forbidden)) {
			t.Fatal("用户列表披露了密码存储字段")
		}
	}
}

func TestPostgresAdminUsersQueryValidationAndAccess(t *testing.T) {
	s, admin, _ := setup(t)
	moderationAdmin(t, s, admin)
	for _, query := range []string{
		"limit=0", "limit=-1", "limit=101", "limit=many", "role=OWNER", "status=PENDING",
		"cursor=not-a-valid-cursor", "cursor=e30", "cursor=" + strings.Repeat("a", 1025),
		"search=" + url.QueryEscape(strings.Repeat("字", 121)),
	} {
		admin.call("GET", "/api/v1/admin/users?"+query, nil, 400, "")
	}
	anonymous := &testClient{t: t, handler: s.Router()}
	anonymous.call("GET", "/api/v1/admin/users", nil, 401, "")
	regular := &testClient{t: t, handler: s.Router(), csrf: admin.csrf}
	registered(t, s, regular, "regular-list-user@example.test")
	regular.call("GET", "/api/v1/admin/users?search=admin", nil, 403, "")
	// 管理员本人仍不能从用户列表停用自己，原状态操作与撤权行为不被分页改写。
	current := readAdminUsersPage(t, admin, "?role=ADMIN")
	admin.call("PATCH", "/api/v1/admin/users/"+current.Data[0].ID, map[string]string{"status": "DISABLED"}, 409, "")
}
