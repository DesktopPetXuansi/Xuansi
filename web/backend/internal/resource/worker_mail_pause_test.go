package resource

import (
	"context"
	"errors"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
	"xuansi/web/backend/internal/platform"
)

// 独立连接事务内建临时表，不触碰真实队列，也不连接 SMTP。
func TestPostgresMailPausePreservesQueueAndOtherJobs(t *testing.T) {
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("需要独立TEST_DATABASE_URL PostgreSQL")
	}
	if !strings.Contains(dsn, "xuansi_test") {
		t.Fatal("测试必须使用xuansi_test隔离库")
	}
	ctx := context.Background()
	db, err := platform.OpenDatabase(ctx, dsn)
	if err != nil {
		t.Fatal("无法连接隔离测试数据库")
	}
	sql, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = sql.Close() })
	tx := db.Begin()
	if tx.Error != nil {
		t.Fatal(tx.Error)
	}
	t.Cleanup(func() { tx.Rollback() })
	if err := tx.Exec(`CREATE TEMP TABLE jobs (
		id uuid PRIMARY KEY, kind text NOT NULL, payload jsonb NOT NULL, status text NOT NULL,
		attempts integer NOT NULL, run_at timestamptz NOT NULL, lease_until timestamptz,
		lease_owner text, last_error text, created_at timestamptz NOT NULL, dedupe_key text
	) ON COMMIT DROP`).Error; err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Add(-time.Minute)
	owner := "previous-worker"
	mail := []platform.Job{
		{ID: uuid.NewString(), Kind: "MAIL", Payload: []byte(`{}`), Status: "QUEUED", Attempts: 2, RunAt: now, CreatedAt: now},
		{ID: uuid.NewString(), Kind: "MAIL", Payload: []byte(`{}`), Status: "RUNNING", Attempts: 3, RunAt: now, CreatedAt: now, LeaseUntil: &now, LeaseOwner: &owner},
	}
	if err := tx.Create(&mail).Error; err != nil {
		t.Fatal(err)
	}
	w := Worker{DB: tx, Config: platform.Config{MailDeliveryDisabled: true}, Owner: "pause-test"}
	for _, kind := range []string{"VALIDATE", "CLEANUP", "FEEDBACK_GITHUB"} {
		job := platform.Job{ID: uuid.NewString(), Kind: kind, Payload: []byte(`{}`), Status: "QUEUED", RunAt: time.Now(), CreatedAt: time.Now()}
		if err := tx.Create(&job).Error; err != nil {
			t.Fatal(err)
		}
		claimed, err := w.claim(ctx)
		if err != nil || claimed.ID != job.ID || claimed.Attempts != 1 {
			t.Fatal("邮件暂停错误阻塞其他任务或领取了邮件")
		}
		if err := tx.Delete(&platform.Job{}, "id=?", claimed.ID).Error; err != nil {
			t.Fatal(err)
		}
	}
	if _, err := w.claim(ctx); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatal("暂停时不应领取剩余邮件")
	}
	for _, original := range mail {
		var actual platform.Job
		if err := tx.First(&actual, "id=?", original.ID).Error; err != nil {
			t.Fatal(err)
		}
		ownerUnchanged := actual.LeaseOwner == nil && original.LeaseOwner == nil || actual.LeaseOwner != nil && original.LeaseOwner != nil && *actual.LeaseOwner == *original.LeaseOwner
		leaseUnchanged := actual.LeaseUntil == nil && original.LeaseUntil == nil || actual.LeaseUntil != nil && original.LeaseUntil != nil && actual.LeaseUntil.Sub(*original.LeaseUntil).Abs() < time.Microsecond
		if actual.Status != original.Status || actual.Attempts != original.Attempts || !ownerUnchanged || !leaseUnchanged {
			t.Fatal("暂停期间邮件状态、次数或租约被改变")
		}
	}
	w.Config.MailDeliveryDisabled = false
	claimed, err := w.claim(ctx)
	if err != nil || claimed.Kind != "MAIL" {
		t.Fatal("恢复开关后原邮件不能正常领取")
	}
}
