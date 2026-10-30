package platform

import (
	"encoding/json"
	"strings"
	"testing"
)

// 统计服务为可选依赖，配置错误明确失败，密钥不进入可序列化配置。
func TestAnalyticsConfigBoundaries(t *testing.T) {
	const website = "126d4d14-5edf-4532-abd1-e08960195f20"
	for _, tc := range []struct {
		name, public, api, key, id, environment string
		valid                                   bool
	}{
		{name: "默认关闭", valid: true},
		{name: "只采集", public: "https://stats.example.test/", id: website, valid: true},
		{name: "只读后台", api: "http://umami:3000", key: "secret", id: website, valid: true},
		{name: "完整配置", public: "https://stats.example.test", api: "http://umami:3000", key: "secret", id: website, environment: "production", valid: true},
		{name: "缺少密钥", api: "http://umami:3000", id: website},
		{name: "缺少网站标识", public: "https://stats.example.test"},
		{name: "无效标识", id: "not-a-uuid"},
		{name: "生产禁止明文采集", public: "http://localhost:3001", id: website, environment: "production"},
		{name: "开发回环采集", public: "http://localhost:3001", id: website, valid: true},
		{name: "禁止同源采集", public: "https://site.example.test", id: website},
		{name: "默认端口仍属同源", public: "https://SITE.example.test:443", id: website},
		{name: "禁止查询串", public: "https://stats.example.test?token=secret", id: website},
		{name: "禁止地址凭据", api: "https://user:secret@stats.example.test", key: "secret", id: website},
		{name: "禁止请求头注入", api: "https://stats.example.test", key: "secret\r\nX-Test: 1", id: website},
	} {
		t.Run(tc.name, func(t *testing.T) {
			config := Config{AppURL: "https://site.example.test", Environment: tc.environment, UmamiPublicURL: tc.public, UmamiAPIURL: tc.api, UmamiAPIKey: tc.key, UmamiWebsiteID: tc.id}
			err := validateAnalytics(&config)
			if (err == nil) != tc.valid {
				t.Fatalf("配置结果不符合边界：%v", err)
			}
			payload, err := json.Marshal(config)
			if err != nil || strings.Contains(string(payload), `"UmamiAPIKey"`) {
				t.Fatal("配置序列化暴露统计密钥字段")
			}
		})
	}
}
