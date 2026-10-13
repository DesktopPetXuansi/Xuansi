package api

import (
	"net/http"
	"net/http/httptest"
	"net/netip"
	"testing"
	"xuansi/web/backend/internal/platform"
)

// 同一可信代理后的访客各自计数，直连访客不能伪造转发头绕过限流。
func TestTrustedProxyRateLimit(t *testing.T) {
	s := &Server{Config: platform.Config{TrustedProxyCIDRs: []netip.Prefix{netip.MustParsePrefix("127.0.0.1/32"), netip.MustParsePrefix("10.0.0.2/32")}}}
	h := s.rateLimit(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) }))
	call := func(remote, forwarded string) int {
		r := httptest.NewRequest("POST", "/api/v1/auth/login", nil)
		r.RemoteAddr = remote
		r.Header.Set("X-Forwarded-For", forwarded)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w.Code
	}
	for i := 0; i < 20; i++ {
		if got := call("127.0.0.1:5000", "198.51.100.1"); got != 204 {
			t.Fatal(got)
		}
	}
	if got := call("127.0.0.1:5000", "198.51.100.1"); got != 429 {
		t.Fatal("首访客未限流")
	}
	if got := call("127.0.0.1:5000", "198.51.100.2"); got != 204 {
		t.Fatal("两个访客共享了额度")
	}
	for i := 0; i < 20; i++ {
		if got := call("192.0.2.5:5000", "203.0.113."+string(rune('A'+i))); got != 204 {
			t.Fatal(got)
		}
	}
	if got := call("192.0.2.5:5000", "198.51.100.99"); got != 429 {
		t.Fatal("不可信转发头绕过限流")
	}
	r := httptest.NewRequest("GET", "/", nil)
	r.RemoteAddr = "127.0.0.1:5000"
	r.Header.Set("X-Forwarded-For", "203.0.113.66, 198.51.100.7, 10.0.0.2")
	if ip := s.clientIP(r); ip != "198.51.100.7" {
		t.Fatalf("未从右向左剥离可信代理：%s", ip)
	}
}
