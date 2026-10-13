package api

import (
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"io"
	"net/http"
	"time"
	"xuansi/web/backend/internal/platform"
)

func (s *Server) authorizeDownload(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	vid, ok := validID(w, r, "versionId")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if res.Status != "ACTIVE" {
		problem(w, r, 403, "RESOURCE_DISABLED", "资源已停用")
		return
	}
	if res.Visibility != "PUBLIC" && (who(r) == nil || !who(r).User.EmailVerified) {
		problem(w, r, 403, "EMAIL_UNVERIFIED", "私有下载需要验证邮箱")
		return
	}
	v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND resource_id=? AND validation_status='READY'", vid, id).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	token := platform.RandomToken()
	ticket := platform.DownloadTicket{ID: uuid.NewString(), ResourceID: id, VersionID: vid, TokenHash: platform.Digest(token), ExpiresAt: time.Now().Add(5 * time.Minute)}
	if i := who(r); i != nil {
		ticket.UserID = &i.User.ID
		if i.GrantID != "" {
			ticket.GrantID = &i.GrantID
		}
	}
	if e = gorm.G[platform.DownloadTicket](s.DB).Create(r.Context(), &ticket); e != nil {
		s.fail(w, r, e)
		return
	}
	reply(w, 200, map[string]interface{}{"url": s.Config.AppURL + "/api/v1/downloads/" + token, "expiresAt": ticket.ExpiresAt, "sha256": v.PackageSHA256, "bytes": v.PackageBytes})
}

// 下载票据每次使用重新检查停用与撤销，票据泄漏窗口最多五分钟。
func (s *Server) download(w http.ResponseWriter, r *http.Request) {
	ticket, e := gorm.G[platform.DownloadTicket](s.DB).Where("token_hash=? AND expires_at>?", platform.Digest(chi.URLParam(r, "ticket")), time.Now()).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	res, e := gorm.G[platform.Resource](s.DB).Where("id=? AND status='ACTIVE'", ticket.ResourceID).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if ticket.UserID == nil && res.Visibility != "PUBLIC" {
		problem(w, r, 403, "FORBIDDEN", "下载授权已失效")
		return
	}
	if ticket.UserID != nil {
		if _, e = gorm.G[platform.User](s.DB).Where("id=? AND status='ACTIVE'", *ticket.UserID).First(r.Context()); e != nil {
			problem(w, r, 403, "FORBIDDEN", "用户已停用")
			return
		}
	}
	if ticket.GrantID != nil {
		if _, e = gorm.G[platform.OAuthGrant](s.DB).Where("id=? AND revoked_at IS NULL", *ticket.GrantID).First(r.Context()); e != nil {
			problem(w, r, 403, "FORBIDDEN", "客户端授权已撤销")
			return
		}
	}
	v, e := gorm.G[platform.ResourceVersion](s.DB).Where("id=? AND validation_status='READY'", ticket.VersionID).First(r.Context())
	if e != nil {
		s.fail(w, r, e)
		return
	}
	body, e := s.Storage.Open(r.Context(), v.PackageKey)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	defer body.Close()
	w.Header().Set("Content-Type", "application/zip")
	w.Header().Set("Content-Disposition", "attachment; filename=resource.zip")
	w.Header().Set("Content-Length", formatBytes(v.PackageBytes))
	if _, e = io.Copy(w, body); e != nil {
		s.Log.Warn("下载中断", "versionId", v.ID)
	}
}
func (s *Server) cover(w http.ResponseWriter, r *http.Request) {
	id, ok := validID(w, r, "id")
	if !ok {
		return
	}
	res, e := s.accessResource(r, id, false)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	if res.CoverKey == nil {
		s.fail(w, r, gorm.ErrRecordNotFound)
		return
	}
	body, e := s.Storage.Open(r.Context(), *res.CoverKey)
	if e != nil {
		s.fail(w, r, e)
		return
	}
	defer body.Close()
	w.Header().Set("Content-Type", "image/png")
	_, _ = io.Copy(w, body)
}
