package api

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"xuansi/web/backend/internal/platform"
)

type analyticsPoint struct {
	Date      string `json:"date"`
	Pageviews int64  `json:"pageviews"`
}

type analyticsTraffic struct {
	Visitors       int64            `json:"visitors"`
	Pageviews      int64            `json:"pageviews"`
	Visits         int64            `json:"visits"`
	DownloadClicks *int64           `json:"downloadClicks"`
	Trend          []analyticsPoint `json:"trend"`
}

type analyticsVersion struct {
	Version  string `json:"version"`
	Filename string `json:"filename"`
	Count    int64  `json:"count"`
}

type analyticsDownloads struct {
	Total    int64              `json:"total"`
	Versions []analyticsVersion `json:"versions"`
}

type analyticsReport struct {
	Range     string              `json:"range"`
	Traffic   *analyticsTraffic   `json:"traffic"`
	Downloads *analyticsDownloads `json:"downloads"`
}

type analyticsCache[T any] struct {
	value   *T
	expires time.Time
}

type analyticsService struct {
	config    platform.Config
	log       *slog.Logger
	client    *http.Client
	githubURL string
	now       func() time.Time
	// 同时请求复用一次来源读取；不同范围共用下载缓存，避免消耗公开 API 额度。
	mu        sync.Mutex
	traffic   map[string]analyticsCache[analyticsTraffic]
	downloads analyticsCache[analyticsDownloads]
}

func newAnalyticsService(config platform.Config, logger *slog.Logger) *analyticsService {
	if logger == nil {
		logger = slog.Default()
	}
	return &analyticsService{
		config: config, log: logger, now: time.Now,
		githubURL: "https://api.github.com/repos/DesktopPetXuansi/Xuansi/releases",
		traffic:   make(map[string]analyticsCache[analyticsTraffic]),
		client: &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error {
			// 统计密钥只发给明确配置的来源，不随重定向流向其他主机。
			return http.ErrUseLastResponse
		}},
	}
}

func (a *analyticsService) report(ctx context.Context, selected string) analyticsReport {
	a.mu.Lock()
	defer a.mu.Unlock()
	now := a.now()
	key := selected + ":" + now.In(analyticsTimezone).Format(time.DateOnly)
	traffic := a.traffic[key]
	downloads := a.downloads
	fetchTraffic := a.config.UmamiAPIURL != "" && a.config.UmamiWebsiteID != "" && a.config.UmamiAPIKey != "" && !now.Before(traffic.expires)
	fetchDownloads := !now.Before(downloads.expires)
	requestCtx := ctx
	ctx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	var trafficErr, clicksErr, downloadsErr error
	var group sync.WaitGroup
	if fetchTraffic {
		group.Go(func() { traffic.value, trafficErr, clicksErr = a.fetchTraffic(ctx, selected, now) })
	}
	if fetchDownloads {
		group.Go(func() { downloads.value, downloadsErr = a.fetchDownloads(ctx) })
	}
	group.Wait()
	// 短暂缓存失败，故障期间刷新后台不会反复打满外部服务；不把失败伪装成零。
	if fetchTraffic && requestCtx.Err() == nil {
		traffic.expires = analyticsExpiry(now, trafficErr)
		for oldKey, entry := range a.traffic {
			if !now.Before(entry.expires) {
				delete(a.traffic, oldKey)
			}
		}
		a.traffic[key] = traffic
	}
	if fetchDownloads && requestCtx.Err() == nil {
		downloads.expires = analyticsExpiry(now, downloadsErr)
		a.downloads = downloads
	}
	if requestCtx.Err() == nil {
		for name, err := range map[string]error{"访问统计": trafficErr, "下载点击统计": clicksErr, "GitHub 下载统计": downloadsErr} {
			if err != nil {
				// 不记录来源响应、URL 或请求头，避免输出统计密钥及内部拓扑。
				a.log.Warn(name + "暂不可用")
			}
		}
	}
	return analyticsReport{Range: selected, Traffic: traffic.value, Downloads: downloads.value}
}

func analyticsExpiry(now time.Time, err error) time.Time {
	if err != nil {
		return now.Add(30 * time.Second)
	}
	return now.Add(5 * time.Minute)
}

// 来源 JSON 限制大小、状态及形状；不信任外部 API 返回的错误正文。
func (a *analyticsService) getJSON(ctx context.Context, address, token string, target interface{}) (http.Header, error) {
	r, err := http.NewRequestWithContext(ctx, http.MethodGet, address, nil)
	if err != nil {
		return nil, errors.New("统计请求无效")
	}
	r.Header.Set("Accept", "application/json")
	r.Header.Set("User-Agent", "Xuansi-Analytics/1.0")
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	response, err := a.client.Do(r)
	if err != nil {
		return nil, errors.New("统计来源连接失败")
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("统计来源暂不可用")
	}
	const limit = 2 << 20
	payload, err := io.ReadAll(io.LimitReader(response.Body, limit+1))
	if err != nil || len(payload) > limit || json.Unmarshal(payload, target) != nil {
		return nil, errors.New("统计来源响应无效")
	}
	return response.Header, nil
}

func (s *Server) adminAnalytics(w http.ResponseWriter, r *http.Request) {
	selected := r.URL.Query().Get("range")
	if selected == "" {
		selected = "7d"
	}
	if selected != "7d" && selected != "30d" && selected != "90d" {
		invalid(w, r, "统计范围仅支持近7天、30天或90天")
		return
	}
	reply(w, http.StatusOK, s.analytics.report(r.Context(), selected))
}

func (s *Server) analyticsConfig(w http.ResponseWriter, r *http.Request) {
	var out struct {
		Enabled   bool    `json:"enabled"`
		WebsiteID *string `json:"websiteId"`
		ScriptURL *string `json:"scriptUrl"`
	}
	if s.Config.UmamiPublicURL != "" && s.Config.UmamiWebsiteID != "" {
		out.Enabled = true
		out.WebsiteID = &s.Config.UmamiWebsiteID
		address := s.Config.UmamiPublicURL + "/script.js"
		out.ScriptURL = &address
	}
	reply(w, http.StatusOK, out)
}
