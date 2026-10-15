package oauth

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"github.com/ory/fosite"
	"github.com/ory/fosite/compose"
	"gorm.io/gorm"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"xuansi/web/backend/internal/platform"
)

type Service struct {
	Provider    fosite.OAuth2Provider
	Store       *Store
	AppURL      string
	CurrentUser func(*http.Request) *platform.User
}

func New(db *gorm.DB, c platform.Config, getUser func(*http.Request) *platform.User) *Service {
	secret := c.OAuthSecret
	if len(secret) < 32 {
		secret = platform.RandomToken()
	}
	config := &fosite.Config{GlobalSecret: []byte(secret), AccessTokenLifespan: 15 * time.Minute, RefreshTokenLifespan: 30 * 24 * time.Hour, AuthorizeCodeLifespan: 5 * time.Minute, EnforcePKCE: true, EnforcePKCEForPublicClients: true, EnablePKCEPlainChallengeMethod: false, RefreshTokenScopes: []string{}, RedirectSecureChecker: func(ctx context.Context, u *url.URL) bool { return validRedirect(u) }}
	store := &Store{DB: db}
	provider := compose.Compose(config, store, compose.NewOAuth2HMACStrategy(config), compose.OAuth2AuthorizeExplicitFactory, compose.OAuth2RefreshTokenGrantFactory, compose.OAuth2PKCEFactory, compose.OAuth2TokenRevocationFactory, compose.OAuth2TokenIntrospectionFactory)
	return &Service{provider, store, c.AppURL, getUser}
}
func validRedirect(u *url.URL) bool {
	if u == nil || u.Scheme != "http" || u.User != nil || u.Path != "/oauth/callback" || u.RawQuery != "" || u.Fragment != "" {
		return false
	}
	ip := net.ParseIP(u.Hostname())
	port, e := strconv.Atoi(u.Port())
	return ip != nil && ip.IsLoopback() && (u.Hostname() == "127.0.0.1" || u.Hostname() == "::1") && e == nil && port > 0 && port <= 65535
}
func (s *Service) Authorize(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 32<<10)
	if e := r.ParseForm(); e != nil {
		http.Error(w, "无效授权请求", 400)
		return
	}
	redirect, e := url.Parse(r.Form.Get("redirect_uri"))
	if e != nil || !validRedirect(redirect) || r.Form.Get("code_challenge_method") != "S256" || !validScopes(r.Form.Get("scope")) || r.Form.Get("response_type") != "code" || len(r.Form.Get("state")) < 8 {
		http.Error(w, "授权参数无效", 400)
		return
	}
	request, e := s.Provider.NewAuthorizeRequest(r.Context(), r)
	if e != nil {
		s.Provider.WriteAuthorizeError(r.Context(), w, request, e)
		return
	}
	user := s.CurrentUser(r)
	if r.Method == "GET" {
		page := "/authorize"
		if user == nil {
			page = "/login"
		}
		next := "/authorize?" + r.URL.RawQuery
		params := r.URL.Query()
		if user == nil {
			params = url.Values{"next": {next}}
		}
		http.Redirect(w, r, s.AppURL+page+"?"+params.Encode(), 302)
		return
	}
	if user == nil || !user.EmailVerified || user.Status != "ACTIVE" {
		http.Error(w, "请登录并验证邮箱", 403)
		return
	}
	if r.Form.Get("consent") != "approve" && r.Form.Get("approve") != "true" {
		http.Error(w, "请明确同意授权", 403)
		return
	}
	grant := platform.OAuthGrant{ID: uuid.NewString(), UserID: user.ID, DeviceLabel: "desktop-ai-pet", CreatedAt: time.Now(), LastSeenAt: time.Now()}
	var response fosite.AuthorizeResponder
	e = s.Store.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		ctx := context.WithValue(r.Context(), txKey{}, tx)
		if e := gorm.G[platform.OAuthGrant](tx).Create(ctx, &grant); e != nil {
			return e
		}
		for _, scope := range request.GetRequestedScopes() {
			request.GrantScope(scope)
		}
		session := &Session{DefaultSession: fosite.DefaultSession{Subject: user.ID, Username: user.Email}, GrantID: grant.ID}
		var e error
		response, e = s.Provider.NewAuthorizeResponse(ctx, request, session)
		return e
	})
	if e != nil {
		s.Provider.WriteAuthorizeError(r.Context(), w, request, e)
		return
	}
	// UI 使用 JSON 接收跳转目标，避免 fetch 追随到客户端回环端口。
	query := redirect.Query()
	for key, values := range response.GetParameters() {
		for _, value := range values {
			query.Add(key, value)
		}
	}
	redirect.RawQuery = query.Encode()
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]interface{}{"data": map[string]string{"redirectUrl": redirect.String()}})
}
func (s *Service) Token(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 32<<10)
	if e := r.ParseForm(); e != nil {
		http.Error(w, "无效令牌请求", 400)
		return
	}
	var request fosite.AccessRequester
	var response fosite.AccessResponder
	var protocolErr error
	// 以提交凭据的摘要加事务锁，使同一授权码/刷新令牌的并发使用串行。
	e := s.Store.DB.WithContext(r.Context()).Transaction(func(tx *gorm.DB) error {
		ctx := context.WithValue(r.Context(), txKey{}, tx)
		key := platform.Digest(r.Form.Get("code") + r.Form.Get("refresh_token"))
		if e := tx.Exec("SELECT pg_advisory_xact_lock(hashtextextended(?,0))", key).Error; e != nil {
			return e
		}
		request, protocolErr = s.Provider.NewAccessRequest(ctx, r, &Session{})
		if protocolErr != nil {
			return nil
		}
		response, protocolErr = s.Provider.NewAccessResponse(ctx, request)
		return protocolErr
	})
	if e != nil {
		protocolErr = e
	}
	if protocolErr != nil {
		s.Provider.WriteAccessError(r.Context(), w, request, protocolErr)
		return
	}
	s.Provider.WriteAccessResponse(r.Context(), w, request, response)
}
func (s *Service) Revoke(w http.ResponseWriter, r *http.Request) {
	r.Body = http.MaxBytesReader(w, r.Body, 32<<10)
	e := s.Provider.NewRevocationRequest(r.Context(), r)
	s.Provider.WriteRevocationResponse(r.Context(), w, e)
}

// 只接受明确的读授权或读写授权；旧只读请求不会自动提升。
func validScopes(raw string) bool {
	scopes := strings.Fields(raw)
	seen := map[string]bool{}
	for _, scope := range scopes {
		if seen[scope] || scope != "resources:read" && scope != "resources:write" {
			return false
		}
		seen[scope] = true
	}
	return seen["resources:read"]
}

func (s *Service) Authenticate(ctx context.Context, token string) (string, string, []string, error) {
	use, request, e := s.Provider.IntrospectToken(ctx, token, fosite.AccessToken, &Session{}, "resources:read")
	if e != nil || use != fosite.AccessToken {
		return "", "", nil, fmt.Errorf("授权失效")
	}
	session, ok := request.GetSession().(*Session)
	if !ok {
		return "", "", nil, fmt.Errorf("会话无效")
	}
	return session.Subject, session.GrantID, append([]string(nil), request.GetGrantedScopes()...), nil
}
