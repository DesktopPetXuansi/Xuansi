-- +goose Up
-- 跨进程共享 GitHub 仓库冷却与短租约；崩溃后租约到期可继续投递。
CREATE TABLE feedback_github_channels (
 repository text PRIMARY KEY,
 not_before timestamptz NOT NULL DEFAULT now(),
 lease_until timestamptz,
 lease_owner uuid,
 CHECK ((lease_until IS NULL) = (lease_owner IS NULL))
);
-- +goose Down
DROP TABLE feedback_github_channels;
