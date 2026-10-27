-- +goose Up
-- 清空垃圾保留幂等骨架，不能由旧投稿请求重新创建；此字段不是 GORM 软删除标记。
ALTER TABLE feedback ADD COLUMN cleared_at timestamptz;
ALTER TABLE feedback DROP CONSTRAINT feedback_title_check, DROP CONSTRAINT feedback_description_check;
ALTER TABLE feedback
 ADD CONSTRAINT feedback_title_check CHECK (char_length(title)>0 OR moderation_status='WITHDRAWN' OR (moderation_status='SPAM' AND cleared_at IS NOT NULL)),
 ADD CONSTRAINT feedback_description_check CHECK (char_length(description)>0 OR moderation_status='WITHDRAWN' OR (moderation_status='SPAM' AND cleared_at IS NOT NULL));

-- +goose Down
-- 回退只转换已清空骨架的关闭状态，不恢复已经清除的用户内容。
UPDATE feedback SET moderation_status='WITHDRAWN' WHERE cleared_at IS NOT NULL AND moderation_status='SPAM';
ALTER TABLE feedback DROP CONSTRAINT feedback_title_check, DROP CONSTRAINT feedback_description_check;
ALTER TABLE feedback
 ADD CONSTRAINT feedback_title_check CHECK (char_length(title)>0 OR moderation_status='WITHDRAWN'),
 ADD CONSTRAINT feedback_description_check CHECK (char_length(description)>0 OR moderation_status='WITHDRAWN');
ALTER TABLE feedback DROP COLUMN cleared_at;
