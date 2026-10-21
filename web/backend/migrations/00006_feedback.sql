-- +goose Up
-- 反馈保持私有，仅收固定诊断字段；幂等编号独立于反馈收据。
CREATE TABLE feedback (
 id uuid PRIMARY KEY,
 idempotency_key uuid NOT NULL UNIQUE,
 request_hash text NOT NULL,
 category text NOT NULL CHECK (category IN ('BUG','SUGGESTION','OTHER')),
 title varchar(80) NOT NULL CHECK (char_length(title)>0),
 description varchar(4000) NOT NULL CHECK (char_length(description)>0),
 contact varchar(160) NOT NULL DEFAULT '',
 diagnostics jsonb,
 status text NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW','IN_PROGRESS','RESOLVED')),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX feedback_recent ON feedback(created_at DESC,id DESC);
CREATE INDEX feedback_status_recent ON feedback(status,created_at DESC,id DESC);
-- +goose Down
DROP TABLE feedback;
