package api

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"gorm.io/gorm"
)

type registrationRateError struct{ Until time.Time }

func (e *registrationRateError) Error() string { return "注册邮件发送过于频繁" }

// 用途域分离，来源和邮箱不明文落入限流表，六位码不能离线穷举普通摘要。
func (s *Server) registrationDigest(purpose string, values ...string) string {
	mac := hmac.New(sha256.New, []byte(s.Config.OAuthSecret))
	mac.Write([]byte("registration:" + purpose + "\x00" + strings.Join(values, "\x00")))
	return hex.EncodeToString(mac.Sum(nil))
}

func (s *Server) registrationQuota(tx *gorm.DB, r *http.Request, email string, now time.Time) error {
	limits := []struct {
		scope, key string
		maximum    int
		cooldown   time.Duration
	}{
		{"EMAIL", s.registrationDigest("email", email), 5, time.Minute},
		{"IP", s.registrationDigest("ip", s.clientIP(r)), 20, 0},
	}
	for _, limit := range limits {
		var accepted struct{ Scope string }
		result := tx.Raw(`INSERT INTO registration_send_limits(scope,key_hash,sends,resets_at,next_send_at)
		 VALUES(?,?,1,?,?) ON CONFLICT(scope,key_hash) DO UPDATE SET
		 sends=CASE WHEN registration_send_limits.resets_at<=? THEN 1 ELSE registration_send_limits.sends+1 END,
		 resets_at=CASE WHEN registration_send_limits.resets_at<=? THEN EXCLUDED.resets_at ELSE registration_send_limits.resets_at END,
		 next_send_at=EXCLUDED.next_send_at
		 WHERE (registration_send_limits.resets_at<=? OR registration_send_limits.sends<?)
		 AND registration_send_limits.next_send_at<=? RETURNING scope`,
			limit.scope, limit.key, now.Add(time.Hour), now.Add(limit.cooldown), now, now, now, limit.maximum, now).Scan(&accepted)
		if result.Error != nil {
			return result.Error
		}
		if accepted.Scope == "" {
			var waiting struct{ Until time.Time }
			if err := tx.Raw(`SELECT greatest(next_send_at,CASE WHEN sends>=? THEN resets_at ELSE next_send_at END) AS until
			 FROM registration_send_limits WHERE scope=? AND key_hash=?`, limit.maximum, limit.scope, limit.key).Scan(&waiting).Error; err != nil {
				return err
			}
			return &registrationRateError{Until: waiting.Until}
		}
	}
	// 按过期索引清理临时记录，不保留长期访客画像；冷却/有效挑战不参与删除。
	if err := tx.Exec(`DELETE FROM registration_send_limits WHERE (scope,key_hash) IN
	 (SELECT scope,key_hash FROM registration_send_limits WHERE resets_at<? ORDER BY resets_at LIMIT 100 FOR UPDATE SKIP LOCKED)`, now.Add(-24*time.Hour)).Error; err != nil {
		return err
	}
	return tx.Exec(`DELETE FROM registration_challenges WHERE email_hash IN
	 (SELECT email_hash FROM registration_challenges WHERE expires_at<? ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED)`, now.Add(-24*time.Hour)).Error
}

func registrationRateProblem(w http.ResponseWriter, r *http.Request, limit *registrationRateError) {
	seconds := max(1, int(math.Ceil(time.Until(limit.Until).Seconds())))
	w.Header().Set("Retry-After", strconv.Itoa(seconds))
	problem(w, r, 429, "REGISTRATION_RATE_LIMITED", "邮件发送较频繁，请稍后重试")
}
