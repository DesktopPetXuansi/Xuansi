// Package feedbackgithub 将已保存的匿名反馈同步到明确授权的 GitHub 仓库。
package feedbackgithub

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

var repositoryPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$`)

type Client struct {
	repository string
	token      string
	public     bool
	http       *http.Client
}

type Submission struct {
	ID, Category, Title, Description, Contact string
	Diagnostics                               map[string]string
	CreatedAt                                 time.Time
	PublicConsent                             bool
}

type Issue struct {
	Number int64
	URL    string
}

// New 固定官方 API 地址、超时及禁止跳转，避免将令牌转发到第三方。
func New(repository, token string, public bool, httpClient *http.Client) (*Client, error) {
	parts := strings.Split(repository, "/")
	if !repositoryPattern.MatchString(repository) || len(parts) != 2 || parts[1] == "." || parts[1] == ".." || token == "" || strings.IndexFunc(token, func(r rune) bool { return r <= 32 || r >= 127 }) >= 0 {
		return nil, &Error{Reason: ReasonConfig, Phase: PhaseConfig, Permanent: true}
	}
	owned := http.Client{}
	if httpClient != nil {
		owned = *httpClient
	}
	owned.Timeout = 15 * time.Second
	owned.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	return &Client{repository: repository, token: token, public: public, http: &owned}, nil
}

type remoteIssue struct {
	Number      int64           `json:"number"`
	URL         string          `json:"html_url"`
	Body        string          `json:"body"`
	PullRequest json.RawMessage `json:"pull_request"`
}

// EnsureIssue 每次先核对可见性，再完整查重；响应丢失后由下一轮查重补偿。
// GitHub 没有创建 Issue 的幂等接口，这里不承诺严格的 exactly-once。
func (c *Client) EnsureIssue(ctx context.Context, in Submission) (Issue, error) {
	id, err := uuid.Parse(in.ID)
	if err != nil || id.String() != in.ID || in.CreatedAt.IsZero() {
		return Issue{}, &Error{Reason: ReasonInvalidSubmission, Phase: PhaseValidation, Permanent: true}
	}
	if c.public && !in.PublicConsent {
		return Issue{}, &Error{Reason: ReasonConsent, Phase: PhaseValidation, Permanent: true}
	}
	var repository struct {
		Private   *bool `json:"private"`
		HasIssues bool  `json:"has_issues"`
	}
	if _, err := c.request(ctx, http.MethodGet, "/repos/"+c.repository, nil, &repository, 200, PhaseRepository); err != nil {
		return Issue{}, err
	}
	if repository.Private == nil || *repository.Private == c.public {
		return Issue{}, &Error{Reason: ReasonVisibility, Phase: PhaseRepository, Permanent: true}
	}
	if !repository.HasIssues {
		return Issue{}, &Error{Reason: ReasonIssuesDisabled, Phase: PhaseRepository, Permanent: true}
	}
	marker := "<!-- feedback-id:" + in.ID + " -->"
	path := "/repos/" + c.repository + "/issues"
	query := url.Values{"state": {"all"}, "sort": {"created"}, "direction": {"asc"}, "per_page": {"100"}, "since": {in.CreatedAt.Add(-5 * time.Minute).UTC().Format(time.RFC3339)}}
	for page := 1; page <= 20; page++ {
		query.Set("page", strconv.Itoa(page))
		var issues []remoteIssue
		header, err := c.request(ctx, http.MethodGet, path+"?"+query.Encode(), nil, &issues, 200, PhaseList)
		if err != nil {
			return Issue{}, err
		}
		if issues == nil {
			return Issue{}, &Error{Reason: ReasonDecode, Phase: PhaseList}
		}
		for _, issue := range issues {
			if len(issue.PullRequest) > 0 && string(issue.PullRequest) != "null" {
				continue
			}
			if issue.Body == marker || strings.HasPrefix(issue.Body, marker+"\n") || strings.HasPrefix(issue.Body, marker+"\r\n") {
				return c.checkedIssue(issue, PhaseList)
			}
		}
		next, err := nextPage(strings.Join(header.Values("Link"), ","), path, page)
		if err != nil {
			return Issue{}, err
		}
		if !next {
			payload := struct {
				Title string `json:"title"`
				Body  string `json:"body"`
			}{Title: issueTitle(in), Body: issueBody(in, marker)}
			var created remoteIssue
			if _, err := c.request(ctx, http.MethodPost, path, payload, &created, 201, PhaseCreate); err != nil {
				return Issue{}, err
			}
			return c.checkedIssue(created, PhaseCreate)
		}
	}
	return Issue{}, &Error{Reason: ReasonPaginationLimit, Phase: PhaseList}
}

func (c *Client) checkedIssue(in remoteIssue, phase Phase) (Issue, error) {
	want := "https://github.com/" + c.repository + "/issues/" + strconv.FormatInt(in.Number, 10)
	if in.Number <= 0 || in.URL != want {
		return Issue{}, &Error{Reason: ReasonInvalidReceipt, Phase: phase}
	}
	return Issue{Number: in.Number, URL: in.URL}, nil
}

// nextPage 只读取可信同路径分页编号，实际请求地址仍由本地重新构建。
func nextPage(link, path string, current int) (bool, error) {
	if link == "" {
		return false, nil
	}
	found := false
	for _, part := range strings.Split(link, ",") {
		sections := strings.Split(strings.TrimSpace(part), ";")
		if len(sections) < 2 {
			return false, &Error{Reason: ReasonPaginationLink, Phase: PhaseList}
		}
		isNext := false
		for _, parameter := range sections[1:] {
			if strings.TrimSpace(parameter) == `rel="next"` {
				isNext = true
			}
		}
		if !isNext {
			continue
		}
		if found {
			return false, &Error{Reason: ReasonPaginationLink, Phase: PhaseList}
		}
		found = true
		target := strings.TrimSpace(sections[0])
		if !strings.HasPrefix(target, "<") || !strings.HasSuffix(target, ">") {
			return false, &Error{Reason: ReasonPaginationLink, Phase: PhaseList}
		}
		u, err := url.Parse(target[1 : len(target)-1])
		if err != nil || u.Scheme != "https" || u.Host != "api.github.com" || u.User != nil || u.Path != path || u.RawPath != "" || u.Fragment != "" {
			return false, &Error{Reason: ReasonPaginationLink, Phase: PhaseList}
		}
		values, err := url.ParseQuery(u.RawQuery)
		if err != nil || len(values["page"]) != 1 || values.Get("page") != strconv.Itoa(current+1) {
			return false, &Error{Reason: ReasonPaginationLink, Phase: PhaseList}
		}
	}
	return found, nil
}
