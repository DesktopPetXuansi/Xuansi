package resource

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/google/uuid"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"xuansi/web/backend/internal/feedbackgithub"
	"xuansi/web/backend/internal/platform"
)

type feedbackPayload struct {
	FeedbackID string `json:"feedbackId"`
}

// 渠道等待不属于投递失败，不消耗任务的远端重试预算。
type feedbackChannelWait struct{ until time.Time }

func (e *feedbackChannelWait) Error() string { return "GitHub 反馈渠道等待冷却或租约释放" }

func (w *Worker) claimFeedbackChannel(ctx context.Context, repository string) (string, error) {
	owner := uuid.NewString()
	var claimed struct{ Repository string }
	err := w.DB.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.Exec("INSERT INTO feedback_github_channels(repository) VALUES (?) ON CONFLICT DO NOTHING", repository).Error; err != nil {
			return err
		}
		result := tx.Raw(`UPDATE feedback_github_channels SET lease_owner=?,lease_until=now()+interval '3 minutes'
			WHERE repository=? AND not_before<=now() AND (lease_until IS NULL OR lease_until<=now()) RETURNING repository`, owner, repository).Scan(&claimed)
		if result.Error != nil {
			return result.Error
		}
		if claimed.Repository != "" {
			return nil
		}
		var waiting struct{ Until time.Time }
		if err := tx.Raw("SELECT greatest(not_before,coalesce(lease_until,not_before)) AS until FROM feedback_github_channels WHERE repository=?", repository).Scan(&waiting).Error; err != nil {
			return err
		}
		return &feedbackChannelWait{until: waiting.Until}
	})
	if err != nil {
		var waiting *feedbackChannelWait
		if errors.As(err, &waiting) {
			return "", waiting
		}
		return "", fmt.Errorf("GitHub 反馈渠道暂时无法领取")
	}
	return owner, nil
}

// 队列只保存编号，正文和联系方式保留在原收件记录中。
func QueueFeedback(ctx context.Context, tx *gorm.DB, id string) error {
	payload, err := json.Marshal(feedbackPayload{FeedbackID: id})
	if err != nil {
		return err
	}
	dedupe := "feedback-github:" + id
	return gorm.G[platform.Job](tx, clause.OnConflict{DoNothing: true}).Create(ctx, &platform.Job{
		ID: uuid.NewString(), Kind: "FEEDBACK_GITHUB", Payload: payload, Status: "QUEUED",
		RunAt: time.Now(), CreatedAt: time.Now(), DedupeKey: &dedupe,
	})
}

func (w *Worker) deliverFeedback(ctx context.Context, payload json.RawMessage) (deliveryErr error) {
	var in feedbackPayload
	if err := json.Unmarshal(payload, &in); err != nil || uuid.Validate(in.FeedbackID) != nil {
		return &feedbackgithub.Error{Reason: feedbackgithub.ReasonInvalidSubmission, Phase: feedbackgithub.PhaseValidation, Permanent: true}
	}
	row, err := gorm.G[platform.FeedbackEntry](w.DB).Where("id=?", in.FeedbackID).First(ctx)
	if err != nil {
		// 数据库错误有时包含字段值，因此仅向任务日志返回固定事件。
		return fmt.Errorf("反馈记录暂时无法读取")
	}
	if row.GitHubIssueNumber > 0 {
		return nil
	}
	if row.GitHubRepository == "" || row.GitHubRepository != w.Config.FeedbackGitHubRepository || row.GitHubPublic != w.Config.FeedbackGitHubPublic {
		return &feedbackgithub.Error{Reason: feedbackgithub.ReasonConfig, Phase: feedbackgithub.PhaseConfig, Permanent: true}
	}
	if row.GitHubPublic && !row.PublicConsent {
		return &feedbackgithub.Error{Reason: feedbackgithub.ReasonConsent, Phase: feedbackgithub.PhaseValidation, Permanent: true}
	}
	client, err := feedbackgithub.New(row.GitHubRepository, w.Config.FeedbackGitHubToken, row.GitHubPublic, w.FeedbackHTTPClient)
	if err != nil {
		return err
	}
	owner, err := w.claimFeedbackChannel(ctx, row.GitHubRepository)
	if err != nil {
		return err
	}
	// 网络期间不持有 SQL 事务；独占租约长于整个任务的两分钟超时。
	defer func() {
		delay := time.Second
		var remote *feedbackgithub.Error
		if errors.As(deliveryErr, &remote) && (remote.Reason == feedbackgithub.ReasonRateLimit || remote.Status == http.StatusTooManyRequests || remote.RetryAfter > 0) {
			_, delay, _ = feedbackRetry(deliveryErr, 1)
		}
		cleanupCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		if err := w.DB.WithContext(cleanupCtx).Exec(`UPDATE feedback_github_channels SET not_before=greatest(not_before,now()+(? * interval '1 second')),lease_owner=NULL,lease_until=NULL WHERE repository=? AND lease_owner=?`, delay.Seconds(), row.GitHubRepository, owner).Error; err != nil {
			w.Log.Warn("GitHub 反馈渠道释放失败", "feedbackId", row.ID)
			if deliveryErr == nil {
				deliveryErr = fmt.Errorf("GitHub 反馈渠道暂时无法释放")
			}
		}
	}()
	diagnostics := map[string]string{}
	if row.Diagnostics != nil {
		diagnostics = map[string]string{"appVersion": row.Diagnostics.AppVersion, "system": row.Diagnostics.System, "architecture": row.Diagnostics.Architecture, "pythonVersion": row.Diagnostics.PythonVersion, "qtVersion": row.Diagnostics.QtVersion}
	}
	issue, err := client.EnsureIssue(ctx, feedbackgithub.Submission{
		ID: row.ID, Category: row.Category, Title: row.Title, Description: row.Description,
		Diagnostics: diagnostics, CreatedAt: row.CreatedAt, PublicConsent: row.PublicConsent,
	})
	if err != nil {
		return err
	}
	if err = w.DB.WithContext(ctx).Model(&platform.FeedbackEntry{}).Where("id=? AND git_hub_issue_number=0", row.ID).Updates(map[string]interface{}{"git_hub_issue_number": issue.Number, "git_hub_issue_url": issue.URL}).Error; err != nil {
		return fmt.Errorf("GitHub 收据暂时无法保存，下次重试先查原 Issue")
	}
	w.Log.Info("反馈已同步 GitHub", "feedbackId", row.ID, "issueNumber", issue.Number)
	return nil
}

// 临时错误最多重试十次；配置/权限错误停止投递，原反馈始终保留以供修复后重试。
func feedbackRetry(err error, attempts int) (string, time.Duration, string) {
	delay := time.Minute
	for i := 1; i < attempts && delay < time.Hour; i++ {
		delay *= 2
	}
	if delay > time.Hour {
		delay = time.Hour
	}
	status, message := "QUEUED", "GitHub 同步暂时失败，将自动重试"
	var remote *feedbackgithub.Error
	if errors.As(err, &remote) {
		if remote.RetryAfter > delay {
			delay = remote.RetryAfter
		}
		if remote.Permanent {
			status, message = "FAILED", "GitHub 同步配置、权限或公开范围校验失败，请修复后重试"
		}
	}
	if attempts >= 10 {
		status, message = "FAILED", "GitHub 同步多次失败，反馈已保留，请检查后重试"
	}
	return status, delay, message
}
