package download

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestFetchResumesAndChecksWholeFile(t *testing.T) {
	content := []byte(strings.Repeat("xuansi", 1000))
	hash := sha256.Sum256(content)
	destination := filepath.Join(t.TempDir(), "bundle.zip")
	if err := os.WriteFile(destination+".part", content[:1200], 0600); err != nil {
		t.Fatal(err)
	}
	requestedRange := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Range") != "bytes=1200-" {
			t.Errorf("unexpected range %q", r.Header.Get("Range"))
			return
		}
		requestedRange = true
		w.Header().Set("Content-Range", fmt.Sprintf("bytes 1200-%d/%d", len(content)-1, len(content)))
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write(content[1200:])
	}))
	defer server.Close()
	if err := Fetch(context.Background(), server.Client(), server.URL, destination, int64(len(content)), hex.EncodeToString(hash[:])); err != nil {
		t.Fatal(err)
	}
	if !requestedRange {
		t.Fatal("partial download was not resumed")
	}
	got, err := os.ReadFile(destination)
	if err != nil || string(got) != string(content) {
		t.Fatalf("downloaded file: %v", err)
	}
}

func TestFetchRejectsChangedOrCorruptResource(t *testing.T) {
	content := []byte(strings.Repeat("a", 100))
	hash := sha256.Sum256(content)
	destination := filepath.Join(t.TempDir(), "bundle.zip")
	if err := os.WriteFile(destination+".part", content[:20], 0600); err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Range") != "bytes=20-" {
			t.Error("missing range")
		}
		_, _ = w.Write([]byte(strings.Repeat("b", len(content))))
	}))
	defer server.Close()
	if err := Fetch(context.Background(), server.Client(), server.URL, destination, int64(len(content)), hex.EncodeToString(hash[:])); err == nil {
		t.Fatal("accepted corrupt resource")
	}
	if _, err := os.Stat(destination); !os.IsNotExist(err) {
		t.Fatalf("published corrupt file: %v", err)
	}
}
