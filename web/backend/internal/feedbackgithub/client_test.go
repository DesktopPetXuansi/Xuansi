package feedbackgithub

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func response(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body)), Header: make(http.Header)}
}
func submission() Submission {
	return Submission{ID: "123e4567-e89b-12d3-a456-426614174000", Category: "BUG", Title: "窗口异常", Description: "@owner\n```\n/close", Contact: "mail@example.test", Diagnostics: map[string]string{"system": "Windows"}, CreatedAt: time.Date(2026, 10, 20, 0, 0, 0, 0, time.UTC)}
}
func client(t *testing.T, f transportFunc) *Client {
	t.Helper()
	c, err := New("owner/repo", "secret-token", false, &http.Client{Transport: f})
	if err != nil {
		t.Fatal(err)
	}
	return c
}
func TestCreatePrivateIssue(t *testing.T) {
	calls := 0
	c := client(t, func(r *http.Request) (*http.Response, error) {
		calls++
		if r.URL.Host != "api.github.com" || r.Header.Get("Authorization") != "Bearer secret-token" || r.Header.Get("X-GitHub-Api-Version") != "2026-03-10" || r.Header.Get("Accept") != "application/vnd.github+json" || r.Header.Get("User-Agent") == "" {
			t.Fatal("missing trusted request headers")
		}
		if calls == 1 {
			return response(200, `{"private":true,"has_issues":true}`), nil
		}
		if calls == 2 {
			q := r.URL.Query()
			if q.Get("state") != "all" || q.Get("since") != "2026-10-19T23:55:00Z" || q.Get("per_page") != "100" {
				t.Fatal(q)
			}
			return response(200, `[]`), nil
		}
		var in struct{ Title, Body string }
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			t.Fatal(err)
		}
		if !strings.HasPrefix(in.Body, "<!-- feedback-id:"+submission().ID+" -->\n") || !strings.Contains(in.Body, "````\n@owner\n```\n/close\n````") || strings.Contains(in.Body, "mail@example.test") || !strings.Contains(in.Body, "Windows") {
			t.Fatal(in)
		}
		if r.Method != http.MethodPost || !strings.HasPrefix(in.Title, "[BUG]") {
			t.Fatal(in)
		}
		return response(201, `{"number":7,"html_url":"https://github.com/owner/repo/issues/7"}`), nil
	})
	issue, err := c.EnsureIssue(context.Background(), submission())
	if err != nil || issue.Number != 7 || calls != 3 {
		t.Fatalf("%+v %v calls=%d", issue, err, calls)
	}
}
func TestRepositoryPrivacyGuard(t *testing.T) {
	for _, body := range []string{`{"private":false,"has_issues":true}`, `{"private":true,"has_issues":false}`, `{}`} {
		t.Run(body, func(t *testing.T) {
			calls := 0
			c := client(t, func(r *http.Request) (*http.Response, error) { calls++; return response(200, body), nil })
			_, err := c.EnsureIssue(context.Background(), submission())
			var target *Error
			if !errors.As(err, &target) || !target.Permanent || calls != 1 {
				t.Fatalf("%v calls=%d", err, calls)
			}
		})
	}
}
func TestClosedIssueAcrossPagesAndSkipPR(t *testing.T) {
	calls := 0
	marker := "<!-- feedback-id:" + submission().ID + " -->\n正文"
	c := client(t, func(r *http.Request) (*http.Response, error) {
		calls++
		if calls == 1 {
			return response(200, `{"private":true,"has_issues":true}`), nil
		}
		if r.Method == http.MethodPost {
			t.Fatal("unexpected POST")
		}
		if calls == 2 {
			b, _ := json.Marshal([]map[string]interface{}{{"body": marker, "number": 3, "pull_request": map[string]string{"url": "x"}}})
			res := response(200, string(b))
			res.Header.Set("Link", `<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"`)
			return res, nil
		}
		if r.URL.Query().Get("page") != "2" || r.URL.Query().Get("since") == "" {
			t.Fatal(r.URL)
		}
		b, _ := json.Marshal([]map[string]interface{}{{"body": marker, "number": 9, "state": "closed", "html_url": "https://github.com/owner/repo/issues/9"}})
		return response(200, string(b)), nil
	})
	got, err := c.EnsureIssue(context.Background(), submission())
	if err != nil || got.Number != 9 || calls != 3 {
		t.Fatalf("%+v %v", got, err)
	}
}
func TestUnsafeOrFailedPaginationNeverCreates(t *testing.T) {
	for _, link := range []string{`<https://evil.test/issues?page=2>; rel="next"`, `<https://api.github.com/repos/other/repo/issues?page=2>; rel="next"`, `<https://api.github.com/repos/owner/repo/issues?page=2>; rel="next"`} {
		t.Run(link, func(t *testing.T) {
			calls := 0
			c := client(t, func(r *http.Request) (*http.Response, error) {
				calls++
				if r.Method == http.MethodPost {
					t.Fatal("unexpected POST")
				}
				if calls == 1 {
					return response(200, `{"private":true,"has_issues":true}`), nil
				}
				if calls == 2 {
					res := response(200, `[]`)
					res.Header.Set("Link", link)
					return res, nil
				}
				return response(500, `secret remote body`), nil
			})
			_, err := c.EnsureIssue(context.Background(), submission())
			if err == nil || strings.Contains(err.Error(), "secret") {
				t.Fatal(err)
			}
			if calls == 3 {
				assertSafeReason(t, err, ReasonHTTP, PhaseList)
			} else {
				assertSafeReason(t, err, ReasonPaginationLink, PhaseList)
			}
		})
	}
}
func TestRateLimitAndSafeErrors(t *testing.T) {
	for _, status := range []int{401, 403, 404, 410, 422, 429, 500} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			c := client(t, func(r *http.Request) (*http.Response, error) {
				res := response(status, `secret-token contact`)
				if status == 429 {
					res.Header.Set("Retry-After", "120")
				}
				return res, nil
			})
			_, err := c.EnsureIssue(context.Background(), submission())
			var target *Error
			if !errors.As(err, &target) || target.Status != status || target.Permanent != (status < 429) || strings.Contains(err.Error(), "secret") {
				t.Fatal(err)
			}
			if status == 429 && target.RetryAfter != 2*time.Minute {
				t.Fatal(target.RetryAfter)
			}
		})
	}
}
func TestUncertainPostRecoveredOnRetry(t *testing.T) {
	created := false
	posts := 0
	c := client(t, func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/repos/owner/repo" {
			return response(200, `{"private":true,"has_issues":true}`), nil
		}
		if r.Method == http.MethodPost {
			posts++
			created = true
			return nil, errors.New("secret network failure")
		}
		if created {
			b, _ := json.Marshal([]map[string]interface{}{{"body": "<!-- feedback-id:" + submission().ID + " -->\n", "number": 2, "html_url": "https://github.com/owner/repo/issues/2"}})
			return response(200, string(b)), nil
		}
		return response(200, `[]`), nil
	})
	if _, err := c.EnsureIssue(context.Background(), submission()); err == nil || strings.Contains(err.Error(), "secret") {
		t.Fatal(err)
	}
	got, err := c.EnsureIssue(context.Background(), submission())
	if err != nil || got.Number != 2 || posts != 1 {
		t.Fatalf("%+v %v posts=%d", got, err, posts)
	}
}
func TestRejectRedirectAndWrongIssueURL(t *testing.T) {
	for _, redirect := range []bool{true, false} {
		calls := 0
		c := client(t, func(r *http.Request) (*http.Response, error) {
			calls++
			if calls == 1 {
				if redirect {
					res := response(302, "")
					res.Header.Set("Location", "https://evil.test")
					return res, nil
				}
				return response(200, `{"private":true,"has_issues":true}`), nil
			}
			if calls == 2 {
				return response(200, `[]`), nil
			}
			return response(201, `{"number":1,"html_url":"https://evil.test/owner/repo/issues/1"}`), nil
		})
		_, err := c.EnsureIssue(context.Background(), submission())
		if err == nil {
			t.Fatal("unsafe response accepted")
		}
		if redirect {
			assertSafeReason(t, err, ReasonHTTP, PhaseRepository)
		} else {
			assertSafeReason(t, err, ReasonInvalidReceipt, PhaseCreate)
		}
		if redirect && calls != 1 {
			t.Fatal("followed redirect")
		}
	}
}
func TestCancellationAndConfiguration(t *testing.T) {
	for _, repo := range []string{"owner/repo/x", "owner/../repo", "owner/repo\r\n", "https://github.com/o/r"} {
		if _, err := New(repo, "token", false, nil); err == nil {
			t.Fatal(repo)
		}
	}
	if _, err := New("owner/repo", "token\r\n", false, nil); err == nil {
		t.Fatal("invalid token")
	}
	c := client(t, func(r *http.Request) (*http.Response, error) { return nil, r.Context().Err() })
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := c.EnsureIssue(ctx, submission()); err == nil {
		t.Fatal("expected cancellation")
	}
}
