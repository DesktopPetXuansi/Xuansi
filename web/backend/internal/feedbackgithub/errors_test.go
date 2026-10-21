package feedbackgithub

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"testing"
)

// 错误日志只能反映固定原因和阶段，不包含远端正文、反馈或凭据。
func TestSafeDistinctFailureReasons(t *testing.T) {
	cases := []struct {
		name      string
		body      string
		transport error
		want      Reason
		phase     Phase
	}{
		{"visibility", `{"private":false,"has_issues":true}`, nil, ReasonVisibility, PhaseRepository},
		{"disabled", `{"private":true,"has_issues":false}`, nil, ReasonIssuesDisabled, PhaseRepository},
		{"decode", `secret-token 反馈 contact`, nil, ReasonDecode, PhaseRepository},
		{"transport", "", errors.New("secret-token 反馈 contact"), ReasonTransport, PhaseRepository},
		{"timeout", "", context.DeadlineExceeded, ReasonTimeout, PhaseRepository},
		{"context", "", context.Canceled, ReasonContext, PhaseRepository},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			c := client(t, func(*http.Request) (*http.Response, error) {
				if tc.transport != nil {
					return nil, tc.transport
				}
				return response(200, tc.body), nil
			})
			_, err := c.EnsureIssue(context.Background(), submission())
			assertSafeReason(t, err, tc.want, tc.phase)
		})
	}
	_, err := New("../secret-token", "secret-token", false, nil)
	assertSafeReason(t, err, ReasonConfig, PhaseConfig)
	c, err := New("owner/repo", "secret-token", true, nil)
	if err != nil {
		t.Fatal(err)
	}
	_, err = c.EnsureIssue(context.Background(), submission())
	assertSafeReason(t, err, ReasonConsent, PhaseValidation)
}

func assertSafeReason(t *testing.T, err error, want Reason, phase Phase) {
	t.Helper()
	var target *Error
	if !errors.As(err, &target) || target.Reason != want || target.Phase != phase {
		t.Fatalf("unexpected safe error: %+v", target)
	}
	message := err.Error()
	if !strings.Contains(message, want.String()) || !strings.Contains(message, phase.String()) {
		t.Fatal(message)
	}
	for _, secret := range []string{"secret-token", "反馈", "contact"} {
		if strings.Contains(message, secret) {
			t.Fatal("error leaked private content")
		}
	}
}

func TestUnknownEnumsCannotInjectErrorLog(t *testing.T) {
	err := &Error{Reason: Reason(255), Phase: Phase(255)}
	if strings.Contains(err.Error(), "255") || !strings.Contains(err.Error(), "unknown") {
		t.Fatal(err)
	}
}
