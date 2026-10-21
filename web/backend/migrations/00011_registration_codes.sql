-- +goose Up
-- 注册挑战不依赖未验证账号，保存带密钥摘要和持久错码次数。
CREATE TABLE registration_challenges (
 email_hash varchar(64) PRIMARY KEY,
 id uuid NOT NULL UNIQUE,
 code_hash varchar(64) NOT NULL,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 5),
 expires_at timestamptz NOT NULL,
 resend_at timestamptz NOT NULL,
 consumed_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX registration_challenges_expiry ON registration_challenges(expires_at);
-- 新旧注册/验证发信共享邮箱冷却和小时额度，重启或多进程不会清零。
CREATE TABLE registration_send_limits (
 scope text NOT NULL CHECK (scope IN ('EMAIL','IP')),
 key_hash varchar(64) NOT NULL,
 sends integer NOT NULL CHECK (sends>0),
 resets_at timestamptz NOT NULL,
 next_send_at timestamptz NOT NULL,
 PRIMARY KEY(scope,key_hash)
);
CREATE INDEX registration_send_limits_expiry ON registration_send_limits(resets_at);

-- +goose Down
DROP TABLE registration_send_limits;
DROP TABLE registration_challenges;
