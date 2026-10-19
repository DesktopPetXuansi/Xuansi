-- +goose Up
-- 历史保留资源快照，不以资源外键阻止资源清理；账号删除仍级联移除个人记录。
CREATE TABLE personal_history (
 user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('APPEARANCE','DOWNLOAD')),
 appearance_kind text CHECK(appearance_kind IN ('DEFAULT','MODEL','IMAGE','ANIMATION')),
 resource_id uuid,
 resource_version_id uuid,
 name varchar(120) NOT NULL,
 version text,
 occurred_at timestamptz NOT NULL,
 device_label varchar(80) NOT NULL,
 request_hash text NOT NULL,
 PRIMARY KEY(user_id,id),
 CHECK ((resource_id IS NULL) = (resource_version_id IS NULL))
);
CREATE INDEX personal_history_recent ON personal_history(user_id,occurred_at DESC,id DESC);
CREATE INDEX personal_history_kind_recent ON personal_history(user_id,kind,occurred_at DESC,id DESC);
-- +goose Down
DROP TABLE personal_history;
