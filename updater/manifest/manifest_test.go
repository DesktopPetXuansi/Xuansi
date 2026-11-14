package manifest

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSignedManifestRejectsTamperingAndDowngrade(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 11, 14, 0, 0, 0, 0, time.UTC)
	value := Payload{Format: 1, KeyID: "test", Version: "0.9.1", Channel: "STABLE", OS: "windows", Arch: "x64", DistributionType: "VERSION_BUNDLE", URL: "https://example.com/bundle.zip", SHA256: strings.Repeat("a", 64), Bytes: 100, Issued: now.Format(time.RFC3339), Expires: now.Add(24 * time.Hour).Format(time.RFC3339), MinFrom: "0.9.0", DataFormat: 1}
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	envelope := Envelope{Payload: base64.StdEncoding.EncodeToString(raw), Signature: hex.EncodeToString(ed25519.Sign(private, raw))}
	keys := map[string]ed25519.PublicKey{"test": public}
	if _, err := Verify(envelope, keys, "0.9.0", now); err != nil {
		t.Fatal(err)
	}
	if _, err := Verify(envelope, keys, "0.9.1", now); err == nil {
		t.Fatal("accepted same version")
	}
	if _, err := Verify(envelope, keys, "0.8.0", now); err == nil {
		t.Fatal("accepted unsupported source version")
	}
	if _, err := Verify(envelope, keys, "0.9.0", now.Add(48*time.Hour)); err == nil {
		t.Fatal("accepted expired manifest")
	}
	envelope.Payload = base64.StdEncoding.EncodeToString(append(raw, ' '))
	if _, err := Verify(envelope, keys, "0.9.0", now); err == nil {
		t.Fatal("accepted changed payload")
	}
}
