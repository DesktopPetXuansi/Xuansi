package platform

import (
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Config 集中验证启动配置，生产环境拒绝明文站点和缺失凭据。
type Config struct {
	Address, DatabaseURL, AppURL, StorageDriver, StoragePath          string
	Environment, SMTPHost, SMTPPort, SMTPFrom, SMTPUser, SMTPPassword string
	S3Endpoint, S3Region, S3Bucket, S3AccessKey, S3SecretKey          string
	S3PublicEndpoint                                                  string
	OAuthSecret                                                       string
	FeedbackGitHubRepository                                          string
	FeedbackGitHubToken                                               string `json:"-"`
	UmamiPublicURL, UmamiAPIURL, UmamiWebsiteID                       string
	UmamiAPIKey                                                       string `json:"-"`
	FeedbackGitHubPublic                                              bool
	MailDeliveryDisabled                                              bool
	MaxUploadBytes, QuotaBytes                                        int64
	TrustedProxyCIDRs                                                 []netip.Prefix
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
func LoadConfig() (Config, error) {
	c := Config{Address: env("HTTP_ADDRESS", "127.0.0.1:8080"), DatabaseURL: os.Getenv("DATABASE_URL"), AppURL: env("APP_URL", "http://localhost:3000"), Environment: env("APP_ENV", "development"), StorageDriver: env("STORAGE_DRIVER", "local"), StoragePath: env("STORAGE_PATH", "./data/storage"), SMTPHost: env("SMTP_HOST", "localhost"), SMTPPort: env("SMTP_PORT", "1025"), SMTPFrom: env("SMTP_FROM", "noreply@localhost"), SMTPUser: os.Getenv("SMTP_USER"), SMTPPassword: os.Getenv("SMTP_PASSWORD"), S3Endpoint: os.Getenv("S3_ENDPOINT"), S3Region: env("S3_REGION", "auto"), S3Bucket: os.Getenv("S3_BUCKET"), S3AccessKey: os.Getenv("S3_ACCESS_KEY_ID"), S3SecretKey: os.Getenv("S3_SECRET_ACCESS_KEY"), OAuthSecret: os.Getenv("OAUTH_SECRET"), MaxUploadBytes: 512 << 20, QuotaBytes: 2 << 30}
	// 后台读写可走内网；浏览器的预签名上传单独使用公网 HTTPS 来源。
	c.S3PublicEndpoint = os.Getenv("S3_PUBLIC_ENDPOINT")
	c.UmamiPublicURL = strings.TrimSpace(os.Getenv("UMAMI_PUBLIC_URL"))
	c.UmamiAPIURL = strings.TrimSpace(os.Getenv("UMAMI_API_URL"))
	c.UmamiWebsiteID = strings.TrimSpace(os.Getenv("UMAMI_WEBSITE_ID"))
	c.UmamiAPIKey = strings.TrimSpace(os.Getenv("UMAMI_API_KEY"))
	if err := validateAnalytics(&c); err != nil {
		return c, err
	}
	// 暂停期间不创建或领取邮件任务；默认保持现有发信行为。
	if raw := os.Getenv("MAIL_DELIVERY_DISABLED"); raw != "" {
		value, err := strconv.ParseBool(raw)
		if err != nil {
			return c, fmt.Errorf("MAIL_DELIVERY_DISABLED 必须为布尔值")
		}
		c.MailDeliveryDisabled = value
	}
	c.FeedbackGitHubRepository = os.Getenv("FEEDBACK_GITHUB_REPOSITORY")
	c.FeedbackGitHubToken = os.Getenv("FEEDBACK_GITHUB_TOKEN")
	if raw := os.Getenv("FEEDBACK_GITHUB_PUBLIC"); raw != "" {
		value, err := strconv.ParseBool(raw)
		if err != nil {
			return c, fmt.Errorf("FEEDBACK_GITHUB_PUBLIC 必须为布尔值")
		}
		c.FeedbackGitHubPublic = value
	}
	if err := validateFeedbackGitHub(c); err != nil {
		return c, err
	}
	for key, dest := range map[string]*int64{"MAX_UPLOAD_BYTES": &c.MaxUploadBytes, "USER_QUOTA_BYTES": &c.QuotaBytes} {
		if s := os.Getenv(key); s != "" {
			v, e := strconv.ParseInt(s, 10, 64)
			if e != nil || v <= 0 {
				return c, fmt.Errorf("%s 必须为正整数", key)
			}
			*dest = v
		}
	}
	if c.DatabaseURL == "" {
		return c, fmt.Errorf("必须配置 DATABASE_URL")
	}
	if raw := strings.TrimSpace(os.Getenv("TRUSTED_PROXY_CIDRS")); raw != "" {
		for _, value := range strings.Split(raw, ",") {
			prefix, e := netip.ParsePrefix(strings.TrimSpace(value))
			if e != nil || prefix.Bits() == 0 {
				return c, fmt.Errorf("TRUSTED_PROXY_CIDRS 必须为明确的代理IP/CIDR，不能信任全部地址")
			}
			c.TrustedProxyCIDRs = append(c.TrustedProxyCIDRs, prefix.Masked())
		}
	}
	u, e := url.Parse(c.AppURL)
	if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Path != "" && u.Path != "/" {
		return c, fmt.Errorf("APP_URL 无效")
	}
	if c.Environment == "production" {
		if u.Scheme != "https" || len(c.OAuthSecret) < 32 || c.StorageDriver != "s3" {
			return c, fmt.Errorf("生产要求 HTTPS、32字符 OAuth 密钥和 S3")
		}
		if !c.MailDeliveryDisabled && c.SMTPHost == "localhost" {
			return c, fmt.Errorf("生产开启邮件时要求 SMTP")
		}
	} else {
		host := u.Hostname()
		if u.Scheme != "https" && !(u.Scheme == "http" && (host == "localhost" || net.ParseIP(host) != nil && net.ParseIP(host).IsLoopback())) {
			return c, fmt.Errorf("开发 HTTP 仅支持回环地址")
		}
	}
	if c.StorageDriver != "local" && c.StorageDriver != "s3" {
		return c, fmt.Errorf("未知存储驱动")
	}
	if c.StorageDriver == "s3" && (c.S3Endpoint == "" || c.S3Bucket == "" || c.S3AccessKey == "" || c.S3SecretKey == "") {
		return c, fmt.Errorf("S3 配置不完整")
	}
	if c.S3PublicEndpoint != "" {
		endpoint, err := url.Parse(c.S3PublicEndpoint)
		if err != nil || endpoint.Host == "" || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" || endpoint.Path != "" && endpoint.Path != "/" || endpoint.Scheme != "https" && (c.Environment == "production" || endpoint.Scheme != "http") {
			return c, fmt.Errorf("S3_PUBLIC_ENDPOINT 必须为独立 HTTP 来源，生产环境必须使用 HTTPS")
		}
		c.S3PublicEndpoint = strings.TrimRight(c.S3PublicEndpoint, "/")
	}
	c.AppURL = strings.TrimRight(c.AppURL, "/")
	return c, nil
}

const SessionLifetime = 7 * 24 * time.Hour

// 公共采集与后台读取可以分别启用；任何部分配置都必须具有明确的网站标识。
func validateAnalytics(c *Config) error {
	if c.UmamiWebsiteID != "" {
		id, err := uuid.Parse(c.UmamiWebsiteID)
		if err != nil {
			return fmt.Errorf("UMAMI_WEBSITE_ID 必须为 UUID")
		}
		c.UmamiWebsiteID = id.String()
	}
	if (c.UmamiAPIURL == "") != (c.UmamiAPIKey == "") {
		return fmt.Errorf("UMAMI_API_URL 和 UMAMI_API_KEY 必须同时配置")
	}
	if (c.UmamiPublicURL != "" || c.UmamiAPIURL != "") && c.UmamiWebsiteID == "" {
		return fmt.Errorf("启用 Umami 必须配置 UMAMI_WEBSITE_ID")
	}
	if strings.ContainsAny(c.UmamiAPIKey, "\r\n") {
		return fmt.Errorf("UMAMI_API_KEY 不能包含换行")
	}
	for name, address := range map[string]*string{"UMAMI_PUBLIC_URL": &c.UmamiPublicURL, "UMAMI_API_URL": &c.UmamiAPIURL} {
		if *address == "" {
			continue
		}
		u, err := url.Parse(*address)
		if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.ForceQuery || u.Fragment != "" || u.Path != "" && u.Path != "/" || u.Scheme != "https" && u.Scheme != "http" {
			return fmt.Errorf("%s 必须为独立 HTTP(S) 来源", name)
		}
		if name == "UMAMI_PUBLIC_URL" && u.Scheme != "https" {
			host := u.Hostname()
			if c.Environment == "production" || host != "localhost" && (net.ParseIP(host) == nil || !net.ParseIP(host).IsLoopback()) {
				return fmt.Errorf("UMAMI_PUBLIC_URL 必须使用 HTTPS，开发 HTTP 仅支持回环地址")
			}
		}
		if name == "UMAMI_PUBLIC_URL" {
			app, parseErr := url.Parse(c.AppURL)
			if parseErr == nil && analyticsOrigin(u) == analyticsOrigin(app) {
				return fmt.Errorf("UMAMI_PUBLIC_URL 必须使用独立统计来源")
			}
		}
		*address = strings.TrimRight(*address, "/")
	}
	return nil
}

func analyticsOrigin(u *url.URL) string {
	port := u.Port()
	if port == "" {
		if u.Scheme == "https" {
			port = "443"
		} else if u.Scheme == "http" {
			port = "80"
		}
	}
	return strings.ToLower(u.Scheme+"://"+u.Hostname()) + ":" + port
}
