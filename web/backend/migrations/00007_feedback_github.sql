-- +goose Up
-- 公开许可和目标在收件时冻结，旧记录保持私有且不会被自动转发。
ALTER TABLE feedback
 ADD COLUMN public_consent boolean NOT NULL DEFAULT false,
 ADD COLUMN git_hub_repository text NOT NULL DEFAULT '',
 ADD COLUMN git_hub_public boolean NOT NULL DEFAULT false,
 ADD COLUMN git_hub_issue_number bigint NOT NULL DEFAULT 0 CHECK (git_hub_issue_number >= 0),
 ADD COLUMN git_hub_issue_url text NOT NULL DEFAULT '';
CREATE UNIQUE INDEX feedback_github_issue ON feedback(git_hub_repository,git_hub_issue_number) WHERE git_hub_issue_number>0;
ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('VALIDATE','MAIL','CLEANUP','FEEDBACK_GITHUB'));
-- +goose Down
-- 已投递的远端 Issue 不随本地迁移回滚而删除。
DELETE FROM jobs WHERE kind='FEEDBACK_GITHUB';
ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('VALIDATE','MAIL','CLEANUP'));
DROP INDEX feedback_github_issue;
ALTER TABLE feedback DROP COLUMN public_consent, DROP COLUMN git_hub_repository,
 DROP COLUMN git_hub_public, DROP COLUMN git_hub_issue_number, DROP COLUMN git_hub_issue_url;
