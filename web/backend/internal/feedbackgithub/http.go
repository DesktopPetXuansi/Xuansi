package feedbackgithub

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

const apiOrigin = "https://api.github.com"
const maxResponseBytes = 8 << 20

func (c *Client) request(ctx context.Context, method, path string, payload interface{}, out interface{}, want int, phase Phase) (http.Header, error) {
	var body io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return nil, &Error{Reason: ReasonEncode, Phase: phase, Permanent: true}
		}
		body = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, apiOrigin+path, body)
	if err != nil {
		return nil, &Error{Reason: ReasonConfig, Phase: phase, Permanent: true}
	}
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2026-03-10")
	req.Header.Set("User-Agent", "Xuansi-Feedback-Sync")
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	res, err := c.http.Do(req)
	if err != nil {
		return nil, transportError(err, phase, ReasonTransport)
	}
	defer res.Body.Close()
	if res.StatusCode != want {
		return nil, responseError(res, phase)
	}
	raw, err := io.ReadAll(io.LimitReader(res.Body, maxResponseBytes+1))
	if err != nil {
		failure := transportError(err, phase, ReasonRead)
		failure.Status = res.StatusCode
		return nil, failure
	}
	if len(raw) > maxResponseBytes || json.Unmarshal(raw, out) != nil {
		return nil, &Error{Status: res.StatusCode, Reason: ReasonDecode, Phase: phase}
	}
	return res.Header, nil
}

func responseError(res *http.Response, phase Phase) *Error {
	wait := time.Duration(0)
	if seconds, err := strconv.ParseInt(res.Header.Get("Retry-After"), 10, 64); err == nil && seconds > 0 && seconds <= int64((1<<63-1)/int64(time.Second)) {
		wait = time.Duration(seconds) * time.Second
	} else if at, err := http.ParseTime(res.Header.Get("Retry-After")); err == nil {
		wait = time.Until(at)
	}
	limited := res.StatusCode == 429 || res.Header.Get("Retry-After") != "" || res.Header.Get("X-RateLimit-Remaining") == "0"
	// 二级限流可能没有限流响应头；只读取固定错误字段用于分类，绝不回传或记录正文。
	if res.StatusCode == http.StatusForbidden && !limited {
		var remote struct {
			Message string `json:"message"`
		}
		if json.NewDecoder(io.LimitReader(res.Body, 16<<10)).Decode(&remote) == nil {
			message := strings.ToLower(remote.Message)
			limited = strings.Contains(message, "secondary rate limit") || strings.Contains(message, "rate limit exceeded")
		}
	}
	if res.Header.Get("X-RateLimit-Remaining") == "0" {
		if epoch, err := strconv.ParseInt(res.Header.Get("X-RateLimit-Reset"), 10, 64); err == nil {
			if reset := time.Until(time.Unix(epoch, 0)); reset > wait {
				wait = reset
			}
		}
	}
	if wait < 0 {
		wait = 0
	}
	permanent := res.StatusCode == 401 || res.StatusCode == 404 || res.StatusCode == 410 || res.StatusCode == 422 || (res.StatusCode == 403 && !limited)
	reason := ReasonHTTP
	if limited {
		reason = ReasonRateLimit
	}
	return &Error{Status: res.StatusCode, RetryAfter: wait, Permanent: permanent, Reason: reason, Phase: phase}
}
