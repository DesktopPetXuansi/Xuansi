package api

import (
	"context"
	"errors"
	"math"
	"net/url"
	"strconv"
	"strings"
)

// GitHub 资产下载计数涵盖所有来源，不等同于官网下载点击或安装人数。
func (a *analyticsService) fetchDownloads(ctx context.Context) (*analyticsDownloads, error) {
	out := &analyticsDownloads{Versions: []analyticsVersion{}}
	for page := 1; page <= 100; page++ {
		address, err := url.Parse(a.githubURL)
		if err != nil {
			return nil, errors.New("下载统计地址无效")
		}
		query := address.Query()
		query.Set("per_page", "100")
		query.Set("page", strconv.Itoa(page))
		address.RawQuery = query.Encode()
		var releases *[]struct {
			Tag        string `json:"tag_name"`
			Draft      *bool  `json:"draft"`
			Prerelease *bool  `json:"prerelease"`
			Assets     *[]struct {
				Name  string `json:"name"`
				Count *int64 `json:"download_count"`
			} `json:"assets"`
		}
		headers, err := a.getJSON(ctx, address.String(), "", &releases)
		if err != nil || releases == nil {
			return nil, errors.New("下载统计读取失败")
		}
		for _, release := range *releases {
			if release.Draft == nil || release.Prerelease == nil {
				return nil, errors.New("下载统计发行元数据缺失")
			}
			if *release.Draft || *release.Prerelease {
				continue
			}
			if release.Tag == "" || release.Assets == nil {
				return nil, errors.New("下载统计附件元数据缺失")
			}
			for _, asset := range *release.Assets {
				if !strings.HasPrefix(asset.Name, "Xuansi-") || !strings.HasSuffix(asset.Name, "-windows-x64-setup.exe") {
					continue
				}
				if asset.Count == nil || *asset.Count < 0 || *asset.Count > math.MaxInt64-out.Total {
					return nil, errors.New("下载统计次数无效")
				}
				out.Total += *asset.Count
				out.Versions = append(out.Versions, analyticsVersion{Version: release.Tag, Filename: asset.Name, Count: *asset.Count})
			}
		}
		// 只读取固定仓库的下一页编号，不跟随 Link 中的任意来源地址。
		if !strings.Contains(headers.Get("Link"), `rel="next"`) {
			return out, nil
		}
	}
	return nil, errors.New("下载统计分页超出限制")
}
