package oauth

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/ory/fosite"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"net/url"
	"time"
	"xuansi/web/backend/internal/platform"
)

type txKey struct{}
type Store struct{ DB *gorm.DB }
type Session struct {
	fosite.DefaultSession
	GrantID string `json:"grantId"`
}

func (s *Session) Clone() fosite.Session {
	clone := *s
	clone.ExpiresAt = map[fosite.TokenType]time.Time{}
	for k, v := range s.ExpiresAt {
		clone.ExpiresAt[k] = v
	}
	return &clone
}

type snapshot struct {
	ID                                                               string
	RequestedAt                                                      time.Time
	RequestedScope, GrantedScope, RequestedAudience, GrantedAudience fosite.Arguments
	Form                                                             url.Values
	Session                                                          *Session
}

func (s *Store) db(ctx context.Context) *gorm.DB {
	if tx, ok := ctx.Value(txKey{}).(*gorm.DB); ok {
		return tx
	}
	return s.DB.WithContext(ctx)
}
func (s *Store) GetClient(ctx context.Context, id string) (fosite.Client, error) {
	if id != "desktop-ai-pet" {
		return nil, fosite.ErrNotFound
	}
	return &fosite.DefaultClient{ID: id, Public: true, RedirectURIs: []string{"http://127.0.0.1/oauth/callback", "http://[::1]/oauth/callback"}, GrantTypes: []string{"authorization_code", "refresh_token"}, ResponseTypes: []string{"code"}, Scopes: []string{"resources:read", "resources:write"}}, nil
}

// 未启用 JWT 客户端认证；拒绝无关接口，避免接受没有持久化去重的断言。
func (s *Store) ClientAssertionJWTValid(context.Context, string) error {
	return fosite.ErrInvalidClient
}
func (s *Store) SetClientAssertionJWT(context.Context, string, time.Time) error {
	return fosite.ErrInvalidClient
}
func (s *Store) put(ctx context.Context, kind, signature string, req fosite.Requester) error {
	session, ok := req.GetSession().(*Session)
	if !ok {
		return fosite.ErrServerError
	}
	form := url.Values{}
	for _, key := range []string{"redirect_uri", "code_challenge", "code_challenge_method"} {
		if value := req.GetRequestForm().Get(key); value != "" {
			form.Set(key, value)
		}
	}
	body, e := json.Marshal(snapshot{req.GetID(), req.GetRequestedAt(), req.GetRequestedScopes(), req.GetGrantedScopes(), req.GetRequestedAudience(), req.GetGrantedAudience(), form, session})
	if e != nil {
		return e
	}
	record := platform.OAuthRecord{Signature: platform.Digest(kind + ":" + signature), Kind: kind, RequestID: req.GetID(), GrantID: session.GrantID, Payload: body, Active: true, CreatedAt: time.Now()}
	return gorm.G[platform.OAuthRecord](s.db(ctx)).Create(ctx, &record)
}
func (s *Store) get(ctx context.Context, kind, signature string) (fosite.Requester, error) {
	record, e := gorm.G[platform.OAuthRecord](s.db(ctx), clause.Locking{Strength: "UPDATE"}).Where("signature=?", platform.Digest(kind+":"+signature)).First(ctx)
	if errors.Is(e, gorm.ErrRecordNotFound) {
		return nil, fosite.ErrNotFound
	}
	if e != nil {
		return nil, e
	}
	var data snapshot
	if e = json.Unmarshal(record.Payload, &data); e != nil {
		return nil, e
	}
	client, _ := s.GetClient(ctx, "desktop-ai-pet")
	req := &fosite.Request{ID: data.ID, RequestedAt: data.RequestedAt, Client: client, RequestedScope: data.RequestedScope, GrantedScope: data.GrantedScope, RequestedAudience: data.RequestedAudience, GrantedAudience: data.GrantedAudience, Form: data.Form, Session: data.Session}
	var enabled bool
	result := s.db(ctx).Raw("SELECT true FROM oauth_grants g JOIN users u ON u.id=g.user_id WHERE g.id=? AND g.revoked_at IS NULL AND u.status='ACTIVE' AND u.email_verified", record.GrantID).Scan(&enabled)
	if result.Error != nil {
		return nil, result.Error
	}
	if !enabled {
		return req, fosite.ErrInactiveToken
	}
	if !record.Active {
		if kind == "CODE" {
			return req, fosite.ErrInvalidatedAuthorizeCode
		}
		return req, fosite.ErrInactiveToken
	}
	return req, nil
}
func (s *Store) deactivate(ctx context.Context, kind, signature string) error {
	_, e := gorm.G[platform.OAuthRecord](s.db(ctx)).Where("signature=?", platform.Digest(kind+":"+signature)).Update(ctx, "active", false)
	return e
}
func (s *Store) CreateAuthorizeCodeSession(ctx context.Context, sig string, r fosite.Requester) error {
	return s.put(ctx, "CODE", sig, r)
}
func (s *Store) GetAuthorizeCodeSession(ctx context.Context, sig string, _ fosite.Session) (fosite.Requester, error) {
	return s.get(ctx, "CODE", sig)
}
func (s *Store) InvalidateAuthorizeCodeSession(ctx context.Context, sig string) error {
	result := s.db(ctx).Exec("UPDATE oauth_records SET active=false WHERE signature=? AND active", platform.Digest("CODE:"+sig))
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected != 1 {
		return fosite.ErrSerializationFailure
	}
	return nil
}
func (s *Store) CreateAccessTokenSession(ctx context.Context, sig string, r fosite.Requester) error {
	return s.put(ctx, "ACCESS", sig, r)
}
func (s *Store) GetAccessTokenSession(ctx context.Context, sig string, _ fosite.Session) (fosite.Requester, error) {
	return s.get(ctx, "ACCESS", sig)
}
func (s *Store) DeleteAccessTokenSession(ctx context.Context, sig string) error {
	return s.deactivate(ctx, "ACCESS", sig)
}
func (s *Store) CreateRefreshTokenSession(ctx context.Context, sig, _ string, r fosite.Requester) error {
	return s.put(ctx, "REFRESH", sig, r)
}
func (s *Store) GetRefreshTokenSession(ctx context.Context, sig string, _ fosite.Session) (fosite.Requester, error) {
	return s.get(ctx, "REFRESH", sig)
}
func (s *Store) DeleteRefreshTokenSession(ctx context.Context, sig string) error {
	return s.deactivate(ctx, "REFRESH", sig)
}
func (s *Store) RotateRefreshToken(ctx context.Context, rid, sig string) error {
	result := s.db(ctx).Exec("UPDATE oauth_records SET active=false WHERE signature=? AND active", platform.Digest("REFRESH:"+sig))
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected != 1 {
		return fosite.ErrSerializationFailure
	}
	return s.db(ctx).Exec("UPDATE oauth_records SET active=false WHERE request_id=? AND kind='ACCESS'", rid).Error
}
func (s *Store) revoke(ctx context.Context, rid string) error {
	if e := s.db(ctx).Exec("UPDATE oauth_records SET active=false WHERE request_id=?", rid).Error; e != nil {
		return e
	}
	return s.db(ctx).Exec("UPDATE oauth_grants SET revoked_at=now() WHERE id IN (SELECT grant_id FROM oauth_records WHERE request_id=?)", rid).Error
}
func (s *Store) RevokeAccessToken(ctx context.Context, rid string) error  { return s.revoke(ctx, rid) }
func (s *Store) RevokeRefreshToken(ctx context.Context, rid string) error { return s.revoke(ctx, rid) }
func (s *Store) CreatePKCERequestSession(ctx context.Context, sig string, r fosite.Requester) error {
	return s.put(ctx, "PKCE", sig, r)
}
func (s *Store) GetPKCERequestSession(ctx context.Context, sig string, _ fosite.Session) (fosite.Requester, error) {
	return s.get(ctx, "PKCE", sig)
}
func (s *Store) DeletePKCERequestSession(ctx context.Context, sig string) error {
	return s.deactivate(ctx, "PKCE", sig)
}
