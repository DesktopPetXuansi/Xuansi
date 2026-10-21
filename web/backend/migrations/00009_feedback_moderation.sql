-- +goose Up
-- 历史记录保持已审核身份，新收件默认待审核；旧投递任务不补建。
ALTER TABLE feedback
 ADD COLUMN moderation_status text NOT NULL DEFAULT 'APPROVED'
   CHECK (moderation_status IN ('PENDING','APPROVED','SPAM','WITHDRAWN','WITHDRAWAL_REQUESTED')),
 ADD COLUMN management_token_hash varchar(64) NOT NULL DEFAULT '',
 ADD COLUMN publication_started_at timestamptz,
 ADD COLUMN client_hash varchar(64) NOT NULL DEFAULT '',
 ADD COLUMN content_hash varchar(64) NOT NULL DEFAULT '';
ALTER TABLE feedback ALTER COLUMN moderation_status SET DEFAULT 'PENDING';
-- 撤回清除正文，只保留幂等收据和审计所需状态。
ALTER TABLE feedback DROP CONSTRAINT feedback_title_check, DROP CONSTRAINT feedback_description_check;
ALTER TABLE feedback ADD CONSTRAINT feedback_title_check CHECK (char_length(title)>0 OR moderation_status='WITHDRAWN'),
 ADD CONSTRAINT feedback_description_check CHECK (char_length(description)>0 OR moderation_status='WITHDRAWN');
CREATE INDEX feedback_moderation_recent ON feedback(moderation_status,created_at DESC,id DESC);
CREATE INDEX feedback_duplicate ON feedback(client_hash,content_hash,created_at DESC);

-- 仅保存访客来源的带密钥摘要；多进程共享额度，重启不清零。
CREATE TABLE feedback_submission_limits (
 client_hash varchar(64) NOT NULL,
 window_kind text NOT NULL CHECK (window_kind IN ('MINUTE','HOUR')),
 submissions integer NOT NULL CHECK (submissions > 0),
 resets_at timestamptz NOT NULL,
 PRIMARY KEY(client_hash,window_kind)
);
CREATE INDEX feedback_limits_expiry ON feedback_submission_limits(resets_at);

-- +goose Down
DROP TABLE feedback_submission_limits;
DROP INDEX feedback_duplicate;
DROP INDEX feedback_moderation_recent;
ALTER TABLE feedback DROP CONSTRAINT feedback_title_check, DROP CONSTRAINT feedback_description_check;
UPDATE feedback SET title='已撤回的反馈',description='用户已撤回' WHERE moderation_status='WITHDRAWN';
ALTER TABLE feedback ADD CONSTRAINT feedback_title_check CHECK (char_length(title)>0),
 ADD CONSTRAINT feedback_description_check CHECK (char_length(description)>0);
ALTER TABLE feedback DROP COLUMN moderation_status, DROP COLUMN management_token_hash,
 DROP COLUMN publication_started_at, DROP COLUMN client_hash, DROP COLUMN content_hash;
