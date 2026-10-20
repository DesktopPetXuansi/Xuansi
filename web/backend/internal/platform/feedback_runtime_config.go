package platform

import (
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// LoadFeedbackConfig 只加载匿名反馈服务需要的配置，避免依赖存储、邮件或 OAuth。
func LoadFeedbackConfig() (Config, error) {
	c := Config{
		Address: env("HTTP_ADDRESS", "127.0.0.1:8189"), DatabaseURL: os.Getenv("DATABASE_URL"),
		AppURL: env("APP_URL", "https://xuansi.kukude.top"), Environment: env("APP_ENV", "production"),
		FeedbackGitHubRepository: os.Getenv("FEEDBACK_GITHUB_REPOSITORY"),
		FeedbackGitHubToken:      os.Getenv("FEEDBACK_GITHUB_TOKEN"),
	}
	if c.DatabaseURL == "" {
		return c, fmt.Errorf("必须配置 DATABASE_URL")
	}
	u, err := url.Parse(c.AppURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" && u.Path != "/" {
		return c, fmt.Errorf("APP_URL 必须为站点 Origin")
	}
	loopback := u.Hostname() == "localhost" || net.ParseIP(u.Hostname()) != nil && net.ParseIP(u.Hostname()).IsLoopback()
	if u.Scheme != "https" && !(c.Environment != "production" && u.Scheme == "http" && loopback) {
		return c, fmt.Errorf("生产反馈要求 HTTPS；开发 HTTP 仅支持回环地址")
	}
	c.AppURL = strings.TrimRight(c.AppURL, "/")
	if raw := strings.TrimSpace(os.Getenv("TRUSTED_PROXY_CIDRS")); raw != "" {
		for _, value := range strings.Split(raw, ",") {
			prefix, err := netip.ParsePrefix(strings.TrimSpace(value))
			if err != nil || prefix.Bits() == 0 {
				return c, fmt.Errorf("必须明确指定可信代理IP/CIDR")
			}
			c.TrustedProxyCIDRs = append(c.TrustedProxyCIDRs, prefix.Masked())
		}
	}
	if raw := os.Getenv("FEEDBACK_GITHUB_PUBLIC"); raw != "" {
		value, err := strconv.ParseBool(raw)
		if err != nil {
			return c, fmt.Errorf("FEEDBACK_GITHUB_PUBLIC 必须为布尔值")
		}
		c.FeedbackGitHubPublic = value
	}
	return c, validateFeedbackGitHub(c)
}
