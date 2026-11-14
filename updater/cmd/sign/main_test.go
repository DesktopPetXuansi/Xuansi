package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

func TestSignedBundleCanBeVerified(t *testing.T) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	key := filepath.Join(root, "private.key")
	bundle := filepath.Join(root, "bundle.zip")
	output := filepath.Join(root, "manifest.json")
	if err := os.WriteFile(key, []byte(hex.EncodeToString(private)), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(bundle, []byte("test bundle"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := sign(key, "test", "0.9.1", "0.9.0", bundle, "https://example.com/bundle.zip", output); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	var envelope manifest.Envelope
	if err := json.Unmarshal(data, &envelope); err != nil {
		t.Fatal(err)
	}
	if _, err := manifest.Verify(envelope, map[string]ed25519.PublicKey{"test": public}, "0.9.0", time.Now()); err != nil {
		t.Fatal(err)
	}
}
