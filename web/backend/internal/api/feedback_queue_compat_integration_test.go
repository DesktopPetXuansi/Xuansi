package api

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/pressly/goose/v3"
	backend "xuansi/web/backend"
	"xuansi/web/backend/internal/platform"
)

// 直接模拟旧 API 写入队列表，验证兼容边界由数据库保障，而非只靠新进程自律。
func insertLegacyFeedbackJob(t *testing.T, s *Server, feedbackID, kind, status string) string {
	t.Helper()
	id := uuid.NewString()
	payload, err := json.Marshal(map[string]string{"feedbackId": feedbackID})
	if err != nil {
		t.Fatal(err)
	}
	if err := s.DB.Exec("INSERT INTO jobs(id,kind,payload,status,dedupe_key) VALUES (?,?,?::jsonb,?,?)", id, kind, string(payload), status, "feedback-github:"+feedbackID).Error; err != nil {
		t.Fatal(err)
	}
	return id
}

func feedbackCompatJob(t *testing.T, s *Server, id string) platform.Job {
	t.Helper()
	var job platform.Job
	if err := s.DB.Where("id=?", id).First(&job).Error; err != nil {
		t.Fatal(err)
	}
	return job
}

// 复现 9bd worker 的真实解析契约：旧键缺失即空编号，在任何网络调用前被 UUID 校验拒绝。
func assertReviewedPayloadRejectsLegacyWorker(t *testing.T, payload json.RawMessage, feedbackID string) {
	t.Helper()
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(payload, &fields); err != nil {
		t.Fatal(err)
	}
	if _, exists := fields["feedbackId"]; exists {
		t.Fatalf("旧 worker 仍能识别未经审核的任务键: %s", payload)
	}
	var reviewedID string
	if err := json.Unmarshal(fields["reviewedFeedbackId"], &reviewedID); err != nil || reviewedID != feedbackID {
		t.Fatalf("新 worker 的审核编号错误: %s err=%v", payload, err)
	}
	var legacy struct {
		FeedbackID string `json:"feedbackId"`
	}
	if err := json.Unmarshal(payload, &legacy); err != nil {
		t.Fatal(err)
	}
	if err := uuid.Validate(legacy.FeedbackID); err == nil {
		t.Fatalf("旧 worker 没有在网络前拒绝编号: %q", legacy.FeedbackID)
	}
}

func TestPostgresFeedbackQueueCompatibilityNormalizesLegacyWrites(t *testing.T) {
	s, _ := setupModeration(t)
	feedbackID := uuid.NewString()
	jobID := insertLegacyFeedbackJob(t, s, feedbackID, "FEEDBACK_GITHUB", "QUEUED")
	assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, jobID).Payload, feedbackID)
	// 旧进程更新 payload 也必须经过相同触发器，不能重新暴露旧键。
	updatedID := uuid.NewString()
	if err := s.DB.Exec(`UPDATE jobs SET payload=jsonb_build_object('feedbackId',?::text) WHERE id=?`, updatedID, jobID).Error; err != nil {
		t.Fatal(err)
	}
	assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, jobID).Payload, updatedID)
	// 只变更 kind 时，原先属于其他任务类型的旧 payload 也必须规范化。
	otherID := uuid.NewString()
	otherJob := insertLegacyFeedbackJob(t, s, otherID, "MAIL", "QUEUED")
	if err := s.DB.Exec("UPDATE jobs SET kind='FEEDBACK_GITHUB' WHERE id=?", otherJob).Error; err != nil {
		t.Fatal(err)
	}
	assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, otherJob).Payload, otherID)
	// 混合格式以新键为准，删除旧键，避免旧进程读取另一个编号绕开审核边界。
	for _, operation := range []string{"INSERT", "UPDATE"} {
		t.Run("mixed_"+operation, func(t *testing.T) {
			legacyID, reviewedID, mixedJob := uuid.NewString(), uuid.NewString(), uuid.NewString()
			payload, err := json.Marshal(map[string]string{"feedbackId": legacyID, "reviewedFeedbackId": reviewedID})
			if err != nil {
				t.Fatal(err)
			}
			if operation == "INSERT" {
				err = s.DB.Exec("INSERT INTO jobs(id,kind,payload,status) VALUES (?,'FEEDBACK_GITHUB',?::jsonb,'QUEUED')", mixedJob, string(payload)).Error
			} else {
				mixedJob = insertLegacyFeedbackJob(t, s, legacyID, "FEEDBACK_GITHUB", "QUEUED")
				err = s.DB.Exec("UPDATE jobs SET payload=?::jsonb WHERE id=?", string(payload), mixedJob).Error
			}
			if err != nil {
				t.Fatal(err)
			}
			assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, mixedJob).Payload, reviewedID)
		})
	}
}

// 仅操作 setup 已验证的 xuansi_test 隔离库；即使断言失败，也在后续测试前恢复最新迁移。
func TestPostgresFeedbackQueueCompatibilityMigratesExistingLegacyJobs(t *testing.T) {
	s, _ := setupModeration(t)
	sql, err := s.DB.DB()
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	t.Cleanup(func() {
		if err := platform.Migrate(ctx, s.DB, backend.Migrations); err != nil {
			t.Errorf("兼容迁移测试未恢复最新 schema: %v", err)
		}
	})
	if err := goose.DownToContext(ctx, sql, "migrations", 9); err != nil {
		t.Fatal(err)
	}
	if version, err := goose.GetDBVersionContext(ctx, sql); err != nil || version != 9 {
		t.Fatalf("未回到旧部署 schema: version=%d err=%v", version, err)
	}
	feedbackID := uuid.NewString()
	jobID := insertLegacyFeedbackJob(t, s, feedbackID, "FEEDBACK_GITHUB", "QUEUED")
	var old struct {
		FeedbackID string `json:"feedbackId"`
	}
	if err := json.Unmarshal(feedbackCompatJob(t, s, jobID).Payload, &old); err != nil || uuid.Validate(old.FeedbackID) != nil {
		t.Fatalf("旧 schema 合成任务没有保留真实旧格式: %+v err=%v", old, err)
	}
	if err := platform.Migrate(ctx, s.DB, backend.Migrations); err != nil {
		t.Fatal(err)
	}
	if version, err := goose.GetDBVersionContext(ctx, sql); err != nil || version < 10 {
		t.Fatalf("兼容迁移未完成: version=%d err=%v", version, err)
	}
	assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, jobID).Payload, feedbackID)
}

// 旧 API 生成的待审核任务在旧 worker 中失败后，人工批准恢复同一持久任务。
func TestPostgresFeedbackQueueCompatibilityApprovalRecoversLegacyFailure(t *testing.T) {
	s, c := setupModeration(t)
	feedbackID := uuid.NewString()
	feedbackCall(t, c, feedbackID, moderationInput("合成旧worker任务恢复", true), 201)
	jobID := insertLegacyFeedbackJob(t, s, feedbackID, "FEEDBACK_GITHUB", "QUEUED")
	assertReviewedPayloadRejectsLegacyWorker(t, feedbackCompatJob(t, s, jobID).Payload, feedbackID)
	// 按旧 worker 校验失败的结果落库，绝不执行真实网络请求。
	if err := s.DB.Exec("UPDATE jobs SET status='FAILED',attempts=10,last_error='synthetic old worker invalid payload' WHERE id=?", jobID).Error; err != nil {
		t.Fatal(err)
	}
	var pending platform.FeedbackEntry
	if err := s.DB.Where("id=?", feedbackID).First(&pending).Error; err != nil || pending.ModerationStatus != "PENDING" {
		t.Fatalf("旧 worker 失败改变了待审核状态: %+v err=%v", pending, err)
	}
	approveFeedbackForDelivery(t, s, c, feedbackID)
	moderationJobCount(t, s, 1)
	recovered := feedbackCompatJob(t, s, jobID)
	if recovered.Status != "QUEUED" || recovered.Attempts != 0 || recovered.LastError != nil || recovered.LeaseOwner != nil || recovered.LeaseUntil != nil {
		t.Fatalf("人工批准没有恢复同一旧任务: %+v", recovered)
	}
	assertReviewedPayloadRejectsLegacyWorker(t, recovered.Payload, feedbackID)
}

// 已批准但未获得公开收据的终态任务可恢复；正在执行或已有收据的任务不能被重复批准扰动。
func TestPostgresFeedbackQueueCompatibilityReapprovalRespectsDeliveryState(t *testing.T) {
	for _, terminal := range []string{"FAILED", "DONE"} {
		t.Run(terminal, func(t *testing.T) {
			s, c := setupModeration(t)
			feedbackID := uuid.NewString()
			feedbackCall(t, c, feedbackID, moderationInput("合成审核任务重试"+terminal, true), 201)
			approveFeedbackForDelivery(t, s, c, feedbackID)
			var job platform.Job
			if err := s.DB.Where("dedupe_key=?", "feedback-github:"+feedbackID).First(&job).Error; err != nil {
				t.Fatal(err)
			}
			if err := s.DB.Exec("UPDATE jobs SET status=?,attempts=8,last_error='synthetic terminal failure',run_at=now()+interval '1 hour' WHERE id=?", terminal, job.ID).Error; err != nil {
				t.Fatal(err)
			}
			approveFeedbackForDelivery(t, s, c, feedbackID)
			moderationJobCount(t, s, 1)
			recovered := feedbackCompatJob(t, s, job.ID)
			if recovered.Status != "QUEUED" || recovered.Attempts != 0 || recovered.LastError != nil || recovered.RunAt.After(time.Now().Add(time.Second)) {
				t.Fatalf("重复批准未恢复未公开的终态任务: %+v", recovered)
			}
			assertReviewedPayloadRejectsLegacyWorker(t, recovered.Payload, feedbackID)
			// 排队任务的退避、次数和错误信息不能被重复审核重置。
			if err := s.DB.Exec("UPDATE jobs SET attempts=3,run_at=now()+interval '15 minutes',last_error='synthetic queued backoff' WHERE id=?", job.ID).Error; err != nil {
				t.Fatal(err)
			}
			queuedBefore := feedbackCompatJob(t, s, job.ID)
			approveFeedbackForDelivery(t, s, c, feedbackID)
			queuedAfter := feedbackCompatJob(t, s, job.ID)
			if queuedAfter.Status != "QUEUED" || queuedAfter.Attempts != queuedBefore.Attempts || !queuedAfter.RunAt.Equal(queuedBefore.RunAt) || queuedAfter.LastError == nil || *queuedAfter.LastError != "synthetic queued backoff" {
				t.Fatalf("重复批准重置排队任务退避: before=%+v after=%+v", queuedBefore, queuedAfter)
			}
			if err := s.DB.Exec("UPDATE jobs SET status='RUNNING',attempts=4,lease_owner='synthetic-active-worker',lease_until=now()+interval '2 minutes' WHERE id=?", job.ID).Error; err != nil {
				t.Fatal(err)
			}
			runningBefore := feedbackCompatJob(t, s, job.ID)
			approveFeedbackForDelivery(t, s, c, feedbackID)
			runningAfter := feedbackCompatJob(t, s, job.ID)
			if runningAfter.Status != "RUNNING" || runningAfter.Attempts != runningBefore.Attempts || runningAfter.LeaseOwner == nil || *runningAfter.LeaseOwner != "synthetic-active-worker" || runningAfter.LeaseUntil == nil || runningBefore.LeaseUntil == nil || !runningAfter.LeaseUntil.Equal(*runningBefore.LeaseUntil) || !runningAfter.RunAt.Equal(runningBefore.RunAt) {
				t.Fatalf("重复批准扰动运行中租约: before=%+v after=%+v", runningBefore, runningAfter)
			}
			// 已取得 Issue 收据，即使调度器记录终态异常，也不能再排队创建。
			if err := s.DB.Exec("UPDATE feedback SET git_hub_issue_number=94,git_hub_issue_url='https://github.com/synthetic/feedback/issues/94' WHERE id=?", feedbackID).Error; err != nil {
				t.Fatal(err)
			}
			if err := s.DB.Exec("UPDATE jobs SET status='FAILED',lease_owner=NULL,lease_until=NULL WHERE id=?", job.ID).Error; err != nil {
				t.Fatal(err)
			}
			publishedBefore := feedbackCompatJob(t, s, job.ID)
			approveFeedbackForDelivery(t, s, c, feedbackID)
			publishedAfter := feedbackCompatJob(t, s, job.ID)
			if publishedAfter.Status != "FAILED" || publishedAfter.Attempts != publishedBefore.Attempts || !publishedAfter.RunAt.Equal(publishedBefore.RunAt) {
				t.Fatalf("已有公开收据的任务被重新排队: before=%+v after=%+v", publishedBefore, publishedAfter)
			}
			moderationJobCount(t, s, 1)
		})
	}
}

// 重试已经批准的失败任务仍须重新验证作者许可和冻结渠道，不能把重试当成授权旁路。
func TestPostgresFeedbackQueueCompatibilityRetryRevalidatesConsentAndDestination(t *testing.T) {
	for _, changed := range []string{"consent", "repository", "visibility"} {
		t.Run(changed, func(t *testing.T) {
			s, c := setupModeration(t)
			feedbackID := uuid.NewString()
			feedbackCall(t, c, feedbackID, moderationInput("合成失败重试授权检查"+changed, true), 201)
			approveFeedbackForDelivery(t, s, c, feedbackID)
			var job platform.Job
			if err := s.DB.Where("dedupe_key=?", "feedback-github:"+feedbackID).First(&job).Error; err != nil {
				t.Fatal(err)
			}
			if err := s.DB.Exec("UPDATE jobs SET status='FAILED',attempts=7,last_error='synthetic authorization retry',run_at=now()+interval '1 hour' WHERE id=?", job.ID).Error; err != nil {
				t.Fatal(err)
			}
			var err error
			switch changed {
			case "consent":
				err = s.DB.Exec("UPDATE feedback SET public_consent=false WHERE id=?", feedbackID).Error
			case "repository":
				err = s.DB.Exec("UPDATE feedback SET git_hub_repository='synthetic/different-feedback' WHERE id=?", feedbackID).Error
			case "visibility":
				err = s.DB.Exec("UPDATE feedback SET git_hub_public=false WHERE id=?", feedbackID).Error
			}
			if err != nil {
				t.Fatal(err)
			}
			before := feedbackCompatJob(t, s, job.ID)
			c.call("POST", "/api/v1/admin/feedback/"+feedbackID+"/moderation", map[string]string{"decision": "APPROVE"}, 409, "")
			after := feedbackCompatJob(t, s, job.ID)
			if after.Status != "FAILED" || after.Attempts != before.Attempts || !after.RunAt.Equal(before.RunAt) || after.LastError == nil || *after.LastError != "synthetic authorization retry" {
				t.Fatalf("未授权重试改变了失败任务: before=%+v after=%+v", before, after)
			}
			moderationJobCount(t, s, 1)
		})
	}
}
