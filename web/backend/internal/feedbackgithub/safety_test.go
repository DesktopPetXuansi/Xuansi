package feedbackgithub

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestPublicRequiresConsentAndMatchingVisibility(t *testing.T) {
	for _, consent := range []bool{false, true} {
		for _, private := range []bool{false, true} {
			t.Run(strconv.FormatBool(consent)+"/"+strconv.FormatBool(private), func(t *testing.T) {
				calls, posts := 0, 0
				c, err := New("owner/repo", "secret-token", true, &http.Client{Transport: transportFunc(func(r *http.Request) (*http.Response, error) {
					calls++
					if calls == 1 {
						return response(200, fmt.Sprintf(`{"private":%t,"has_issues":true}`, private)), nil
					}
					if r.Method == http.MethodGet {
						return response(200, `[]`), nil
					}
					posts++
					body, _ := io.ReadAll(r.Body)
					if strings.Contains(string(body), submission().Contact) {
						t.Fatal("contact leaked")
					}
					return response(201, `{"number":1,"html_url":"https://github.com/owner/repo/issues/1"}`), nil
				})})
				if err != nil {
					t.Fatal(err)
				}
				in := submission()
				in.PublicConsent = consent
				_, err = c.EnsureIssue(context.Background(), in)
				if consent && !private {
					if err != nil || posts != 1 {
						t.Fatalf("%v %d", err, posts)
					}
					return
				}
				var target *Error
				if !errors.As(err, &target) || !target.Permanent || posts != 0 {
					t.Fatalf("%v %d", err, posts)
				}
				if !consent && calls != 0 {
					t.Fatal("contacted GitHub without consent")
				}
			})
		}
	}
}

func TestPaginationLimitAndMalformedResponse(t *testing.T) {
	for _, malformed := range []bool{false, true} {
		calls := 0
		c := client(t, func(r *http.Request) (*http.Response, error) {
			calls++
			if calls == 1 {
				return response(200, `{"private":true,"has_issues":true}`), nil
			}
			if r.Method == http.MethodPost {
				t.Fatal("created issue without completing scan")
			}
			if malformed {
				return response(200, `invalid`), nil
			}
			page, _ := strconv.Atoi(r.URL.Query().Get("page"))
			res := response(200, `[]`)
			res.Header.Set("Link", fmt.Sprintf(`<https://api.github.com/repos/owner/repo/issues?page=%d>; rel="next"`, page+1))
			return res, nil
		})
		_, err := c.EnsureIssue(context.Background(), submission())
		if err == nil {
			t.Fatal("expected retryable failure")
		}
		if malformed {
			assertSafeReason(t, err, ReasonDecode, PhaseList)
		} else {
			assertSafeReason(t, err, ReasonPaginationLimit, PhaseList)
		}
		if !malformed && calls != 21 {
			t.Fatal(calls)
		}
	}
}

func TestNullIssueListNeverCreates(t *testing.T) {
	calls := 0
	c := client(t, func(r *http.Request) (*http.Response, error) {
		calls++
		if calls == 1 {
			return response(200, `{"private":true,"has_issues":true}`), nil
		}
		if r.Method == http.MethodPost {
			t.Fatal("null is not a completed issue scan")
		}
		return response(200, `null`), nil
	})
	if _, err := c.EnsureIssue(context.Background(), submission()); err == nil {
		t.Fatal("accepted null list")
	}
}

func TestRateLimitDatesAndReset(t *testing.T) {
	for _, reset := range []bool{false, true} {
		c := client(t, func(r *http.Request) (*http.Response, error) {
			res := response(403, `private remote text`)
			if reset {
				res.Header.Set("X-RateLimit-Remaining", "0")
				res.Header.Set("X-RateLimit-Reset", strconv.FormatInt(time.Now().Add(5*time.Minute).Unix(), 10))
			} else {
				res.Header.Set("Retry-After", time.Now().Add(5*time.Minute).UTC().Format(http.TimeFormat))
			}
			return res, nil
		})
		_, err := c.EnsureIssue(context.Background(), submission())
		var target *Error
		if !errors.As(err, &target) || target.Permanent || target.RetryAfter < 4*time.Minute || target.RetryAfter > 5*time.Minute {
			t.Fatalf("%+v", target)
		}
	}
}

func TestSecondaryRateLimitWithoutHeaders(t *testing.T) {
	c := client(t, func(r *http.Request) (*http.Response, error) {
		return response(403, `{"message":"You have exceeded a secondary rate limit. secret-token"}`), nil
	})
	_, err := c.EnsureIssue(context.Background(), submission())
	var target *Error
	if !errors.As(err, &target) || target.Permanent || strings.Contains(err.Error(), "secret-token") {
		t.Fatalf("%+v", target)
	}
}
