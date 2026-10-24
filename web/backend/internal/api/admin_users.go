package api

import (
	"encoding/base64"
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
	"xuansi/web/backend/internal/platform"

	"github.com/google/uuid"
	"gorm.io/gorm"
)

type adminUserCursor struct {
	At time.Time `json:"at"`
	ID string    `json:"id"`
}

type adminUserListMeta struct {
	NextCursor *string `json:"nextCursor"`
	Total      int64   `json:"total"`
}

// 搜索作用于全站账号；固定时间和ID排序让后续页不会被新注册账号挤乱。
func (s *Server) adminUsers(w http.ResponseWriter, r *http.Request) {
	params := r.URL.Query()
	limit := 20
	if raw := params.Get("limit"); raw != "" {
		value, err := strconv.Atoi(raw)
		if err != nil || value < 1 || value > 100 {
			invalid(w, r, "每页数量须为1至100")
			return
		}
		limit = value
	}
	search := strings.TrimSpace(params.Get("search"))
	role, status := params.Get("role"), params.Get("status")
	if !utf8.ValidString(search) || utf8.RuneCountInString(search) > 120 || (role != "" && role != "USER" && role != "ADMIN") || (status != "" && status != "ACTIVE" && status != "DISABLED") {
		invalid(w, r, "用户筛选条件无效，关键词最多120个字")
		return
	}
	var after adminUserCursor
	if raw := params.Get("cursor"); raw != "" {
		if len(raw) > 1024 {
			invalid(w, r, "分页位置无效，请返回第一页")
			return
		}
		decoded, err := base64.RawURLEncoding.DecodeString(raw)
		if err != nil || json.Unmarshal(decoded, &after) != nil || after.At.IsZero() {
			invalid(w, r, "分页位置无效，请返回第一页")
			return
		}
		if _, err := uuid.Parse(after.ID); err != nil {
			invalid(w, r, "分页位置无效，请返回第一页")
			return
		}
	}
	query := gorm.G[platform.User](s.DB).Where("1=1")
	if search != "" {
		// 参数化之外还转义LIKE元字符，输入百分号只查找真正包含百分号的昵称。
		literal := strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(search)
		pattern := "%" + literal + "%"
		query = query.Where("(display_name ILIKE ? OR email ILIKE ?)", pattern, pattern)
	}
	if role != "" {
		query = query.Where("role = ?", role)
	}
	if status != "" {
		query = query.Where("status = ?", status)
	}
	total, err := query.Count(r.Context(), "*")
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if after.ID != "" {
		query = query.Where("(created_at, id) < (?, ?)", after.At, after.ID)
	}
	rows, err := query.Order("created_at DESC, id DESC").Limit(limit + 1).Find(r.Context())
	if err != nil {
		s.fail(w, r, err)
		return
	}
	var next *string
	if len(rows) > limit {
		rows = rows[:limit]
		last := rows[len(rows)-1]
		cursor, _ := json.Marshal(adminUserCursor{At: last.CreatedAt, ID: last.ID})
		encoded := base64.RawURLEncoding.EncodeToString(cursor)
		next = &encoded
	}
	out := make([]platform.UserView, 0, len(rows))
	for _, user := range rows {
		out = append(out, user.View())
	}
	s.Log.InfoContext(r.Context(), "管理员用户列表已读取", "count", len(out), "hasNextPage", next != nil)
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(struct {
		Data []platform.UserView `json:"data"`
		Meta adminUserListMeta   `json:"meta"`
	}{Data: out, Meta: adminUserListMeta{next, total}})
}
