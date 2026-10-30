package api

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"xuansi/web/backend/internal/platform"
)

const analyticsTestWebsiteID = "126d4d14-5edf-4532-abd1-e08960195f20"

func analyticsFixture(t *testing.T, handler http.HandlerFunc) (*analyticsService, *bytes.Buffer) {
	t.Helper()
	upstream := httptest.NewServer(handler)
	t.Cleanup(upstream.Close)
	var logs bytes.Buffer
	service := newAnalyticsService(platform.Config{
		AppURL: "https://site.example.test", UmamiAPIURL: upstream.URL,
		UmamiWebsiteID: analyticsTestWebsiteID, UmamiAPIKey: "private-analytics-key",
	}, slog.New(slog.NewTextHandler(&logs, nil)))
	service.githubURL = upstream.URL + "/releases"
	service.now = func() time.Time { return time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC) }
	return service, &logs
}

// 使用真实 HTTP 边界验证分页、正式安装包过滤及跨日期范围复用缓存。
func TestAnalyticsGitHubDownloadsAndCache(t *testing.T) {
	var requests atomic.Int32
	service, _ := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.URL.Path != "/releases" || r.URL.Query().Get("per_page") != "100" {
			t.Error("GitHub 请求没有固定仓库路径与分页大小")
		}
		if r.Header.Get("Authorization") != "" {
			t.Error("Umami 密钥泄漏给 GitHub")
		}
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Query().Get("page") == "1" {
			w.Header().Set("Link", `<https://api.github.com/ignored?page=2>; rel="next"`)
			io.WriteString(w, `[
				{"tag_name":"v0.9.0","draft":false,"prerelease":false,"assets":[{"name":"Xuansi-0.9.0-windows-x64-setup.exe","download_count":3},{"name":"SHA256SUMS.txt","download_count":50}]},
				{"tag_name":"v1.0.0","draft":true,"prerelease":false,"assets":[{"name":"Xuansi-1.0.0-windows-x64-setup.exe","download_count":100}]},
				{"tag_name":"v1.0.0-beta","draft":false,"prerelease":true,"assets":[{"name":"Xuansi-1.0.0-beta-windows-x64-setup.exe","download_count":100}]}]`)
			return
		}
		io.WriteString(w, `[{"tag_name":"v0.8.0","draft":false,"prerelease":false,"assets":[{"name":"Xuansi-0.8.0-windows-x64-setup.exe","download_count":5}]}]`)
	})
	service.config.UmamiAPIURL = ""
	for _, selected := range []string{"7d", "30d"} {
		report := service.report(context.Background(), selected)
		if report.Traffic != nil || report.Downloads == nil || report.Downloads.Total != 8 || len(report.Downloads.Versions) != 2 {
			t.Fatalf("下载量未过滤正式安装包或未保留未配置的访问统计：%+v", report)
		}
		if report.Downloads.Versions[0].Version != "v0.9.0" || report.Downloads.Versions[0].Count != 3 {
			t.Fatal("版本顺序或版本下载量不正确")
		}
	}
	if requests.Load() != 2 {
		t.Fatalf("下载总量未跨日期范围复用缓存：请求 %d 次", requests.Load())
	}
}

// 最新稳定版原始响应来自 Umami v3.4.1；日趋势按北京时间补齐零访问日期。
func TestAnalyticsUmamiTrafficAndClicks(t *testing.T) {
	var umamiRequests atomic.Int32
	service, _ := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/releases" {
			io.WriteString(w, `[]`)
			return
		}
		umamiRequests.Add(1)
		query := r.URL.Query()
		if r.Header.Get("Authorization") != "Bearer private-analytics-key" || query.Get("timezone") != "Asia/Shanghai" || query.Get("unit") != "day" {
			t.Error("Umami 认证或时区缺失")
		}
		if query.Get("startAt") != "1792684800000" || query.Get("endAt") != "1793275200000" || query.Get("hostname") != "site.example.test" {
			t.Errorf("日期范围或站点筛选不正确：%s", r.URL.RawQuery)
		}
		switch {
		case strings.HasSuffix(r.URL.Path, "/stats"):
			io.WriteString(w, `{"pageviews":40,"visitors":12,"visits":17,"comparison":{}}`)
		case strings.HasSuffix(r.URL.Path, "/pageviews"):
			io.WriteString(w, `{"pageviews":[{"x":"2026-10-23 00:00:00","y":10},{"x":"2026-10-29 00:00:00","y":30}],"sessions":[]}`)
		case strings.HasSuffix(r.URL.Path, "/metrics"):
			if query.Get("type") != "event" || query.Get("event") != "installer_download" {
				t.Error("下载点击未按唯一事件过滤")
			}
			io.WriteString(w, `[{"x":"installer_download","y":7}]`)
		default:
			t.Errorf("未知 Umami 路径：%s", r.URL.Path)
			w.WriteHeader(404)
		}
	})
	report := service.report(context.Background(), "7d")
	if report.Traffic == nil || report.Traffic.Visitors != 12 || report.Traffic.Pageviews != 40 || report.Traffic.Visits != 17 || report.Traffic.DownloadClicks == nil || *report.Traffic.DownloadClicks != 7 {
		t.Fatalf("Umami 汇总不正确：%+v", report.Traffic)
	}
	if trend := report.Traffic.Trend; len(trend) != 7 || trend[0].Date != "2026-10-23" || trend[0].Pageviews != 10 || trend[1].Pageviews != 0 || trend[6].Pageviews != 30 {
		t.Fatalf("北京时间日趋势不正确：%+v", trend)
	}
	service.report(context.Background(), "7d")
	if umamiRequests.Load() != 3 {
		t.Fatal("相同范围的访问统计没有缓存")
	}
}

// 单个来源失败不伪造为零，点击来源失败也不抹掉仍可读取的访问汇总。
func TestAnalyticsPartialFailures(t *testing.T) {
	for _, failed := range []string{"github", "stats", "metrics"} {
		t.Run(failed, func(t *testing.T) {
			service, logs := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				if failed == "github" && r.URL.Path == "/releases" || failed == "stats" && strings.HasSuffix(r.URL.Path, "/stats") || failed == "metrics" && strings.HasSuffix(r.URL.Path, "/metrics") {
					w.WriteHeader(503)
					io.WriteString(w, `{"error":"private-analytics-key"}`)
					return
				}
				switch {
				case r.URL.Path == "/releases":
					io.WriteString(w, `[]`)
				case strings.HasSuffix(r.URL.Path, "/stats"):
					io.WriteString(w, `{"pageviews":0,"visitors":0,"visits":0}`)
				case strings.HasSuffix(r.URL.Path, "/pageviews"):
					io.WriteString(w, `{"pageviews":[],"sessions":[]}`)
				case strings.HasSuffix(r.URL.Path, "/metrics"):
					io.WriteString(w, `[]`)
				}
			})
			report := service.report(context.Background(), "7d")
			if (report.Downloads == nil) != (failed == "github") || (report.Traffic == nil) != (failed == "stats") {
				t.Fatal("一个数据源失败影响了独立来源")
			}
			if failed == "metrics" && (report.Traffic == nil || report.Traffic.DownloadClicks != nil) {
				t.Fatal("点击失败必须只显示点击不可用")
			}
			if strings.Contains(logs.String(), "private-analytics-key") || !strings.Contains(logs.String(), "统计") {
				t.Fatal("失败未写安全诊断日志或泄漏来源密钥")
			}
		})
	}
}

func TestAnalyticsAdminPermissionsAndRange(t *testing.T) {
	var requests atomic.Int32
	service, _ := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		io.WriteString(w, `[]`)
	})
	service.config.UmamiAPIURL = ""
	s := &Server{analytics: service, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
	router := s.Router()
	for _, tc := range []struct {
		name, role, grant, query string
		status                   int
	}{
		{"匿名", "", "", "", 401}, {"普通用户", "USER", "", "", 403},
		{"客户端授权", "ADMIN", "client-grant", "", 403},
		{"非法范围", "ADMIN", "", "?range=365d", 400},
		{"管理员默认范围", "ADMIN", "", "", 200},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", "/api/v1/admin/analytics"+tc.query, nil)
			if tc.role != "" {
				r = r.WithContext(context.WithValue(r.Context(), identityKey{}, &Identity{User: platform.User{Role: tc.role}, GrantID: tc.grant}))
			}
			w := httptest.NewRecorder()
			router.ServeHTTP(w, r)
			if w.Code != tc.status || w.Header().Get("Cache-Control") != "no-store" {
				t.Fatalf("权限/范围边界错误：%d %s", w.Code, w.Body.String())
			}
			if tc.status == 200 && data[analyticsReport](t, w.Body.Bytes()).Range != "7d" {
				t.Fatal("默认统计范围不正确")
			}
		})
	}
	if requests.Load() != 1 {
		t.Fatal("未授权或无效请求触发了外部统计读取")
	}
}

// 公开采集配置不得把读取统计的私钥或内网 API 地址发送给浏览器。
func TestAnalyticsPublicConfigPrivacy(t *testing.T) {
	for _, enabled := range []bool{false, true} {
		config := platform.Config{UmamiAPIURL: "http://internal-umami:3000", UmamiAPIKey: "private-analytics-key"}
		if enabled {
			config.UmamiPublicURL, config.UmamiWebsiteID = "https://stats.example.test", analyticsTestWebsiteID
		}
		s := &Server{Config: config, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}
		w := httptest.NewRecorder()
		s.Router().ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/analytics/config", nil))
		var response struct {
			Data struct {
				Enabled   bool    `json:"enabled"`
				WebsiteID *string `json:"websiteId"`
				ScriptURL *string `json:"scriptUrl"`
			} `json:"data"`
		}
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &response) != nil || response.Data.Enabled != enabled {
			t.Fatal("公开采集配置未正确表达启用状态")
		}
		if enabled && (response.Data.WebsiteID == nil || *response.Data.WebsiteID != analyticsTestWebsiteID || response.Data.ScriptURL == nil || *response.Data.ScriptURL != "https://stats.example.test/script.js") {
			t.Fatal("公开采集配置不完整")
		}
		if !enabled && (response.Data.WebsiteID != nil || response.Data.ScriptURL != nil) || strings.Contains(w.Body.String(), "private-analytics-key") || strings.Contains(w.Body.String(), "internal-umami") {
			t.Fatal("公开配置泄漏秘密或未启用时暴露残留配置")
		}
	}
}

func TestAnalyticsRejectMalformedUmami(t *testing.T) {
	for _, payload := range []string{`{}`, `{"pageviews":-1,"visitors":2,"visits":3}`, `{"pageviews":"40","visitors":2,"visits":3}`, `null`} {
		service, _ := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/releases" || strings.HasSuffix(r.URL.Path, "/metrics") {
				io.WriteString(w, `[]`)
			} else if strings.HasSuffix(r.URL.Path, "/pageviews") {
				io.WriteString(w, `{"pageviews":[]}`)
			} else {
				io.WriteString(w, payload)
			}
		})
		if report := service.report(context.Background(), "7d"); report.Traffic != nil || report.Downloads == nil {
			t.Fatal("错误响应形状被伪装成零访问")
		}
	}
}

// 来源返回 null、错误类型或负数时，后台必须表达不可用，不能发布错误的累计量。
func TestAnalyticsRejectMalformedGitHub(t *testing.T) {
	for _, payload := range []string{`null`, `{}`, `[{"tag_name":"v0.9.0","draft":false,"prerelease":false,"assets":[{"name":"Xuansi-0.9.0-windows-x64-setup.exe","download_count":-1}]}]`} {
		service, _ := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) { io.WriteString(w, payload) })
		service.config.UmamiAPIURL = ""
		if report := service.report(context.Background(), "7d"); report.Downloads != nil {
			t.Fatal("错误下载响应被作为有效统计")
		}
	}
}

// 外部重定向不得转发读取统计的 Bearer 密钥，也不得把第三方错误正文写进日志。
func TestAnalyticsDoesNotFollowRedirects(t *testing.T) {
	var forwarded atomic.Int32
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { forwarded.Add(1) }))
	defer target.Close()
	service, logs := analyticsFixture(t, func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, target.URL, http.StatusTemporaryRedirect)
	})
	if report := service.report(context.Background(), "7d"); report.Traffic != nil || report.Downloads != nil || forwarded.Load() != 0 {
		t.Fatal("外部重定向被跟随或失败统计被显示成零")
	}
	if strings.Contains(logs.String(), "private-analytics-key") {
		t.Fatal("统计日志泄漏读取密钥")
	}
}
