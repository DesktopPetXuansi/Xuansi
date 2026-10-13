-- +goose Up
-- 替换封面时回收旧封面占用，版本包仍按不可变版本保留。
ALTER TABLE resources ADD COLUMN cover_bytes bigint NOT NULL DEFAULT 0 CHECK(cover_bytes>=0);
-- +goose Down
ALTER TABLE resources DROP COLUMN cover_bytes;
