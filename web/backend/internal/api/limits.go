package api

import (
	"net"
	"net/http"
	"net/netip"
	"strings"
	"sync"
	"time"
)

type rateWindow struct {
	Count int
	Until time.Time
}

// 只有显式可信代理可以传递访客IP；生产反向代理也应设置外层限流。
func (s *Server) rateLimit(next http.Handler) http.Handler {
	var mu sync.Mutex
	windows := map[string]rateWindow{}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		feedback := r.Method == "POST" && r.URL.Path == "/api/v1/feedback"
		management := r.Method == "POST" && strings.HasPrefix(r.URL.Path, "/api/v1/feedback/")
		if !feedback && !management && (!(strings.HasPrefix(r.URL.Path, "/api/v1/auth/") || r.URL.Path == "/oauth/token") || r.Method == "GET") {
			next.ServeHTTP(w, r)
			return
		}
		host := s.clientIP(r)
		key := host + ":" + r.URL.Path
		if management {
			// 管理与撤回独立计数，轮换反馈编号不能绕过凭据尝试的限流。
			key = host + ":feedback-management"
		}
		now := time.Now()
		mu.Lock()
		if len(windows) > 10000 {
			for k, v := range windows {
				if now.After(v.Until) {
					delete(windows, k)
				}
			}
		}
		window := windows[key]
		if now.After(window.Until) {
			window = rateWindow{Until: now.Add(time.Minute)}
		}
		window.Count++
		windows[key] = window
		maximum := 20
		if feedback {
			// 外层抑制无效请求洪泛；有效新收件由数据库执行5次/分钟与20次/小时限制。
			maximum = 60
		}
		allowed := window.Count <= maximum
		mu.Unlock()
		if !allowed {
			w.Header().Set("Retry-After", "60")
			problem(w, r, 429, "RATE_LIMITED", "请求过于频繁，请稍后重试")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) trustedProxy(ip netip.Addr) bool {
	for _, prefix := range s.Config.TrustedProxyCIDRs {
		if prefix.Contains(ip.Unmap()) {
			return true
		}
	}
	return false
}

// 从最近代理向外剥离可信节点，客户端自己追加在左侧的伪造值不会优先。
func (s *Server) clientIP(r *http.Request) string {
	host, _, e := net.SplitHostPort(r.RemoteAddr)
	if e != nil {
		host = r.RemoteAddr
	}
	peer, e := netip.ParseAddr(host)
	if e != nil {
		return host
	}
	peer = peer.Unmap()
	if !s.trustedProxy(peer) {
		return peer.String()
	}
	raw := r.Header.Get("X-Forwarded-For")
	if raw == "" || len(raw) > 1024 {
		return peer.String()
	}
	parts := strings.Split(raw, ",")
	if len(parts) > 16 {
		return peer.String()
	}
	ips := make([]netip.Addr, len(parts))
	for i, part := range parts {
		ip, e := netip.ParseAddr(strings.TrimSpace(part))
		if e != nil {
			return peer.String()
		}
		ips[i] = ip.Unmap()
	}
	for i := len(ips) - 1; i >= 0; i-- {
		if !s.trustedProxy(ips[i]) {
			return ips[i].String()
		}
	}
	return ips[0].String()
}
