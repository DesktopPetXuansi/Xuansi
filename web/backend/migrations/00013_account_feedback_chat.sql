-- +goose Up
-- 所有权仅由网站会话建立；旧匿名记录保留匿名署名。
ALTER TABLE feedback ADD COLUMN owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
 ADD COLUMN submitter_name text NOT NULL DEFAULT '',
 ADD COLUMN admin_read_at timestamptz, ADD COLUMN admin_read_id uuid,
 ADD COLUMN owner_read_at timestamptz, ADD COLUMN owner_read_id uuid;
ALTER TABLE feedback_messages ADD COLUMN author_name text NOT NULL DEFAULT '';
CREATE INDEX feedback_owner_threads ON feedback(owner_user_id,updated_at DESC,id DESC);
CREATE INDEX feedback_chat_threads ON feedback(updated_at DESC,id DESC);
-- +goose Down
DROP INDEX feedback_chat_threads;
DROP INDEX feedback_owner_threads;
ALTER TABLE feedback_messages DROP COLUMN author_name;
ALTER TABLE feedback DROP COLUMN owner_user_id, DROP COLUMN submitter_name,
 DROP COLUMN admin_read_at,DROP COLUMN admin_read_id,DROP COLUMN owner_read_at,DROP COLUMN owner_read_id;
