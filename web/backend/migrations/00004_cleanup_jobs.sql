-- +goose Up
ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('VALIDATE','MAIL','CLEANUP'));
-- +goose Down
DELETE FROM jobs WHERE kind='CLEANUP';
ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN ('VALIDATE','MAIL'));
