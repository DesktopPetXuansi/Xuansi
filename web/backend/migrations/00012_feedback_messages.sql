-- +goose Up
-- 正文与请求收据分离；撤回清空正文仍保留不可恢复的幂等骨架。
CREATE TABLE feedback_messages (
 id uuid PRIMARY KEY,
 feedback_id uuid NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
 author_role text NOT NULL CHECK (author_role IN ('ADMIN','USER')),
 body text NOT NULL CHECK (char_length(body)<=4000),
 created_at timestamptz NOT NULL,
 idempotency_key uuid NOT NULL,
 request_hash varchar(64) NOT NULL,
 UNIQUE(feedback_id,author_role,idempotency_key)
);
CREATE INDEX feedback_messages_page ON feedback_messages(feedback_id,created_at DESC,id DESC);
-- 复用已有持久额度结构，以独立摘要 namespace 区分新收件与私信额度。
-- +goose Down
DROP TABLE feedback_messages;
