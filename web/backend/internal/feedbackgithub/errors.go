package feedbackgithub

import (
	"context"
	"errors"
	"fmt"
	"net"
	"time"
)

// Reason 使用数值枚举，避免调用方将任意敏感字符串带入错误日志。
type Reason uint8

const (
	ReasonUnknown Reason = iota
	ReasonConfig
	ReasonInvalidSubmission
	ReasonConsent
	ReasonVisibility
	ReasonIssuesDisabled
	ReasonTransport
	ReasonTimeout
	ReasonContext
	ReasonDecode
	ReasonRead
	ReasonPaginationLimit
	ReasonPaginationLink
	ReasonInvalidReceipt
	ReasonEncode
	ReasonHTTP
	ReasonRateLimit
)

func (r Reason) String() string {
	names := [...]string{"unknown", "config", "invalid_submission", "consent", "visibility", "issues_disabled", "transport", "timeout", "context", "decode", "read", "pagination_limit", "pagination_link", "invalid_receipt", "encode", "http", "rate_limit"}
	if int(r) >= len(names) {
		return names[0]
	}
	return names[r]
}

// Phase 指明失败所在的固定操作阶段，不包含 URL 或反馈内容。
type Phase uint8

const (
	PhaseUnknown Phase = iota
	PhaseConfig
	PhaseValidation
	PhaseRepository
	PhaseList
	PhaseCreate
)

func (p Phase) String() string {
	names := [...]string{"unknown", "config", "validation", "repository", "list", "create"}
	if int(p) >= len(names) {
		return names[0]
	}
	return names[p]
}

// Error 仅包含可安全进入日志的状态，不能附带令牌、反馈正文或远端错误正文。
type Error struct {
	Status     int
	RetryAfter time.Duration
	Permanent  bool
	Reason     Reason
	Phase      Phase
}

func (e *Error) Error() string {
	return fmt.Sprintf("GitHub feedback request failed (phase=%s reason=%s HTTP=%d)", e.Phase, e.Reason, e.Status)
}

// transportError 分类网络、超时及取消，但不保留原始错误，防止其携带请求信息。
func transportError(err error, phase Phase, fallback Reason) *Error {
	reason := fallback
	var timeout net.Error
	switch {
	case errors.Is(err, context.Canceled):
		reason = ReasonContext
	case errors.Is(err, context.DeadlineExceeded):
		reason = ReasonTimeout
	case errors.As(err, &timeout) && timeout.Timeout():
		reason = ReasonTimeout
	}
	return &Error{Reason: reason, Phase: phase}
}
