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
)

// Config 集中验证启动配置，生产环境拒绝明文站点和缺失凭据。
type Config struct {
	Address, DatabaseURL, AppURL, StorageDriver, StoragePath          string
	Environment, SMTPHost, SMTPPort, SMTPFrom, SMTPUser, SMTPPassword string
	S3Endpoint, S3Region, S3Bucket, S3AccessKey, S3SecretKey          string
	OAuthSecret                                                       string
	FeedbackGitHubRepository                                          string
	FeedbackGitHubToken                                               string `json:"-"`
	FeedbackGitHubPublic                                              bool
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
		if u.Scheme != "https" || c.SMTPHost == "localhost" || len(c.OAuthSecret) < 32 || c.StorageDriver != "s3" {
			return c, fmt.Errorf("生产要求 HTTPS、SMTP、32字符 OAuth 密钥和 S3")
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
	c.AppURL = strings.TrimRight(c.AppURL, "/")
	return c, nil
}

const SessionLifetime = 7 * 24 * time.Hour
