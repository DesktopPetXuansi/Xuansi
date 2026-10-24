-- +goose Up
-- 支持管理员按注册时间、ID稳定翻页，不改变已有账号和会话。
CREATE INDEX users_admin_page ON users (created_at DESC, id DESC);

-- +goose Down
DROP INDEX users_admin_page;
