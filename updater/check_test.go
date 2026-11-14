package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

func TestCheckUpdatesTrustsSignedPayloadOnly(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	value := manifest.Payload{Format: 1, KeyID: "test", Version: "0.9.1", Channel: "STABLE", OS: "windows", Arch: "x64", DistributionType: "VERSION_BUNDLE", URL: "https://example.com/bundle.zip", SHA256: strings.Repeat("a", 64), Bytes: 100, Issued: now.Format(time.RFC3339), Expires: now.Add(time.Hour).Format(time.RFC3339), MinFrom: "0.9.0", DataFormat: 1}
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	signed := base64.StdEncoding.EncodeToString(raw)
	signature := hex.EncodeToString(ed25519.Sign(private, raw))
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"data": []any{map[string]any{"version": "9.9.9", "artifacts": []any{map[string]any{"distributionType": "VERSION_BUNDLE", "updateManifest": signed, "updateSignature": signature}}}}})
	}))
	defer server.Close()
	keys := map[string]ed25519.PublicKey{"test": public}
	candidate, err := checkUpdates(server.Client(), server.URL, "0.9.0", keys, now)
	if err != nil || candidate == nil || candidate.Version != "0.9.1" {
		t.Fatalf("candidate %+v: %v", candidate, err)
	}
	if _, err := checkUpdates(server.Client(), server.URL, "0.9.0", nil, now); err == nil {
		t.Fatal("accepted untrusted release")
	}
}
