package api

import (
	"context"
	"errors"
	"math"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"
)

// 统计日固定采用北京时间；此范围内上海时区不涉及夏令时变更。
var analyticsTimezone = time.FixedZone("Asia/Shanghai", 8*60*60)

func (a *analyticsService) fetchTraffic(ctx context.Context, selected string, now time.Time) (*analyticsTraffic, error, error) {
	days, _ := strconv.Atoi(strings.TrimSuffix(selected, "d"))
	local := now.In(analyticsTimezone)
	start := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, analyticsTimezone).AddDate(0, 0, 1-days)
	query := url.Values{"startAt": {strconv.FormatInt(start.UnixMilli(), 10)}, "endAt": {strconv.FormatInt(now.UnixMilli(), 10)}, "unit": {"day"}, "timezone": {"Asia/Shanghai"}}
	if site, err := url.Parse(a.config.AppURL); err == nil && site.Hostname() != "" {
		query.Set("hostname", site.Hostname())
	}
	base := strings.TrimRight(a.config.UmamiAPIURL, "/") + "/api/websites/" + url.PathEscape(a.config.UmamiWebsiteID)
	var summary struct {
		Visitors  *int64 `json:"visitors"`
		Pageviews *int64 `json:"pageviews"`
		Visits    *int64 `json:"visits"`
	}
	var series struct {
		Pageviews *[]struct {
			Date  string `json:"x"`
			Count *int64 `json:"y"`
		} `json:"pageviews"`
	}
	var events *[]struct {
		Name  string `json:"x"`
		Count *int64 `json:"y"`
	}
	var summaryErr, seriesErr, clicksErr error
	var group sync.WaitGroup
	group.Go(func() { _, summaryErr = a.getJSON(ctx, base+"/stats?"+query.Encode(), a.config.UmamiAPIKey, &summary) })
	group.Go(func() {
		_, seriesErr = a.getJSON(ctx, base+"/pageviews?"+query.Encode(), a.config.UmamiAPIKey, &series)
	})
	group.Go(func() {
		clickQuery, _ := url.ParseQuery(query.Encode())
		clickQuery.Set("type", "event")
		clickQuery.Set("event", "installer_download")
		_, clicksErr = a.getJSON(ctx, base+"/metrics?"+clickQuery.Encode(), a.config.UmamiAPIKey, &events)
	})
	group.Wait()
	valid := func(count *int64) bool { return count != nil && *count >= 0 }
	if summaryErr != nil || seriesErr != nil || !valid(summary.Visitors) || !valid(summary.Pageviews) || !valid(summary.Visits) || series.Pageviews == nil {
		return nil, errors.New("访问统计响应无效"), clicksErr
	}
	out := &analyticsTraffic{Visitors: *summary.Visitors, Pageviews: *summary.Pageviews, Visits: *summary.Visits, Trend: make([]analyticsPoint, days)}
	indices := make(map[string]int, days)
	for index := range days {
		date := start.AddDate(0, 0, index).Format(time.DateOnly)
		out.Trend[index].Date = date
		indices[date] = index
	}
	for _, point := range *series.Pageviews {
		date, err := analyticsDate(point.Date)
		index, exists := indices[date]
		if err != nil || !exists || !valid(point.Count) || *point.Count > math.MaxInt64-out.Trend[index].Pageviews {
			return nil, errors.New("访问趋势响应无效"), clicksErr
		}
		out.Trend[index].Pageviews += *point.Count
	}
	if clicksErr == nil && events != nil {
		var clicks int64
		for _, event := range *events {
			if event.Name != "installer_download" || !valid(event.Count) || *event.Count > math.MaxInt64-clicks {
				clicksErr = errors.New("下载点击统计响应无效")
				break
			}
			clicks += *event.Count
		}
		if clicksErr == nil {
			out.DownloadClicks = &clicks
		}
	} else if clicksErr == nil {
		clicksErr = errors.New("下载点击统计响应缺失")
	}
	return out, nil, clicksErr
}

func analyticsDate(value string) (string, error) {
	for _, layout := range []string{time.DateOnly, "2006-01-02 15:04:05", time.RFC3339} {
		if parsed, err := time.ParseInLocation(layout, value, analyticsTimezone); err == nil {
			return parsed.In(analyticsTimezone).Format(time.DateOnly), nil
		}
	}
	return "", errors.New("访问趋势日期无效")
}
