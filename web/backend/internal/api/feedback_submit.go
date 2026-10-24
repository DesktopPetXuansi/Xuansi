package api

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

var errFeedbackConflict = errors.New("反馈请求编号冲突")
var errFeedbackDuplicate = errors.New("短时间内的重复反馈")

func feedbackDigest(value []byte) string {
	sum := sha256.Sum256(value)
	return hex.EncodeToString(sum[:])
}

func validFeedbackToken(token string) bool {
	decoded, err := hex.DecodeString(token)
	return err == nil && len(decoded) == 32 && hex.EncodeToString(decoded) == token
}

func (s *Server) createFeedback(w http.ResponseWriter, r *http.Request) {
	s.createFeedbackFor(w, r, false)
}

func (s *Server) createAccountFeedback(w http.ResponseWriter, r *http.Request) {
	s.createFeedbackFor(w, r, true)
}

func (s *Server) createFeedbackFor(w http.ResponseWriter, r *http.Request, account bool) {
	key := r.Header.Get("Idempotency-Key")
	if !canonicalFeedbackID(key) {
		invalid(w, r, "请求编号必须为标准UUID")
		return
	}
	var in feedbackInput
	if account {
		var v struct {
			Category      string               `json:"category"`
			Title         string               `json:"title"`
			Description   string               `json:"description"`
			Contact       string               `json:"contact"`
			Diagnostics   *feedbackDiagnostics `json:"diagnostics"`
			PublicConsent bool                 `json:"publicConsent,omitempty"`
		}
		if !decodeFeedback(w, r, &v) {
			return
		}
		in = feedbackInput{Category: v.Category, Title: v.Title, Description: v.Description, Contact: v.Contact, Diagnostics: v.Diagnostics, PublicConsent: v.PublicConsent}
	} else if !decodeFeedback(w, r, &in) {
		return
	}
	if !in.normalize() {
		invalid(w, r, "请检查反馈类型及内容长度")
		return
	}
	if account && in.ManagementToken != "" {
		invalid(w, r, "账号反馈无需管理凭据")
		return
	}
	body, _ := json.Marshal(in)
	if account {
		body, _ = json.Marshal(struct {
			Input feedbackInput
			Actor string
		}{in, who(r).User.ID})
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	// 带密钥摘要代替持久保存原始 IP；生产沿用现有 OAuth 服务密钥。
	mac := hmac.New(sha256.New, []byte(s.Config.OAuthSecret))
	if account {
		mac.Write([]byte("feedback-account:" + who(r).User.ID))
	} else {
		mac.Write([]byte(s.clientIP(r)))
	}
	content, _ := json.Marshal([]string{in.Category, in.Title, in.Description})
	row := feedbackEntry{ID: key, IdempotencyKey: key, RequestHash: feedbackDigest(body),
		Category: in.Category, Title: in.Title, Description: in.Description, Contact: in.Contact,
		Diagnostics: in.Diagnostics, PublicConsent: in.PublicConsent, ModerationStatus: "PENDING",
		Status: "NEW", CreatedAt: now, UpdatedAt: now, ClientHash: hex.EncodeToString(mac.Sum(nil)),
		ContentHash: feedbackDigest(content)}
	if account {
		uid := who(r).User.ID
		row.OwnerUserID = &uid
		row.SubmitterName = who(r).User.DisplayName
	}
	if in.ManagementToken != "" {
		row.ManagementTokenHash = feedbackDigest([]byte(in.ManagementToken))
	}
	if s.Config.FeedbackGitHubRepository != "" && in.PublicConsent {
		row.GitHubRepository, row.GitHubPublic = s.Config.FeedbackGitHubRepository, s.Config.FeedbackGitHubPublic
	}
	status := http.StatusCreated
	err := s.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		result := tx.Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "idempotency_key"}}, DoNothing: true}).Create(&row)
		if result.Error != nil {
			return result.Error
		}
		if result.RowsAffected == 0 {
			var old feedbackEntry
			if err := tx.Where("idempotency_key=?", key).First(&old).Error; err != nil {
				return err
			}
			if old.RequestHash != row.RequestHash || (account && (old.OwnerUserID == nil || *old.OwnerUserID != who(r).User.ID)) || (!account && old.OwnerUserID != nil) {
				return errFeedbackConflict
			}
			row, status = old, http.StatusOK
			return nil
		}
		// 额度与收件一同提交，失败回滚；相同请求的重试不重复消费额度。
		if err := reserveFeedbackQuota(tx, row.ClientHash, now); err != nil {
			return err
		}
		var count int64
		if err := tx.Model(&feedbackEntry{}).Where("id<>? AND client_hash=? AND content_hash=? AND created_at>? AND moderation_status<>'WITHDRAWN'", row.ID, row.ClientHash, row.ContentHash, now.Add(-10*time.Minute)).Count(&count).Error; err != nil {
			return err
		}
		if count > 0 {
			return errFeedbackDuplicate
		}
		return nil
	})
	var limited *feedbackQuotaError
	switch {
	case errors.As(err, &limited):
		w.Header().Set("Retry-After", strconv.Itoa(limited.retryAfter))
		problem(w, r, 429, "RATE_LIMITED", "提交过于频繁，请稍后再试")
	case errors.Is(err, errFeedbackConflict):
		problem(w, r, 409, "CONFLICT", "此请求编号已经用于其他反馈")
	case errors.Is(err, errFeedbackDuplicate):
		problem(w, r, 409, "DUPLICATE_FEEDBACK", "相同反馈已收到，请勿重复提交")
	case err != nil:
		s.feedbackFailure(w, r)
	default:
		s.Log.Info("反馈提交已确认，等待审核", "feedbackId", row.ID)
		// 保持桌面客户端三字段收据，审核或撤回不改变最初收件结果。
		reply(w, status, feedbackReceipt{row.ID, row.CreatedAt.UTC(), "NEW"})
	}
}

type feedbackQuotaError struct{ retryAfter int }

func (e *feedbackQuotaError) Error() string { return "反馈提交频率超过限制" }

// 条件 UPSERT 对每个来源的额度串行化，多进程与并发请求共享同一限制。
func reserveFeedbackQuota(tx *gorm.DB, clientHash string, now time.Time) error {
	return reserveFeedbackQuotaWithLimits(tx, clientHash, now, 5, 20)
}

// 账号聊天独立于投稿额度，支持连续对话，仍由数据库在多进程间限频。
func reserveFeedbackChatQuota(tx *gorm.DB, clientHash string, now time.Time) error {
	return reserveFeedbackQuotaWithLimits(tx, clientHash, now, 30, 300)
}

func reserveFeedbackQuotaWithLimits(tx *gorm.DB, clientHash string, now time.Time, minuteLimit, hourLimit int) error {
	for _, window := range []struct {
		kind     string
		limit    int
		duration time.Duration
	}{{"MINUTE", minuteLimit, time.Minute}, {"HOUR", hourLimit, time.Hour}} {
		var result struct{ Submissions int }
		query := tx.Raw(`INSERT INTO feedback_submission_limits(client_hash,window_kind,submissions,resets_at)
		 VALUES(?,?,1,?) ON CONFLICT(client_hash,window_kind) DO UPDATE SET
		 submissions=CASE WHEN feedback_submission_limits.resets_at<=? THEN 1 ELSE feedback_submission_limits.submissions+1 END,
		 resets_at=CASE WHEN feedback_submission_limits.resets_at<=? THEN EXCLUDED.resets_at ELSE feedback_submission_limits.resets_at END
		 WHERE feedback_submission_limits.resets_at<=? OR feedback_submission_limits.submissions<? RETURNING submissions`,
			clientHash, window.kind, now.Add(window.duration), now, now, now, window.limit).Scan(&result)
		if query.Error != nil {
			return query.Error
		}
		if result.Submissions == 0 {
			return &feedbackQuotaError{retryAfter: int(window.duration.Seconds())}
		}
	}
	// 有索引且每次最多清64条过期计数，不让临时防刷元数据无限积累。
	return tx.Exec(`DELETE FROM feedback_submission_limits WHERE (client_hash,window_kind) IN
	 (SELECT client_hash,window_kind FROM feedback_submission_limits WHERE resets_at<? ORDER BY resets_at LIMIT 64)`, now.Add(-24*time.Hour)).Error
}
