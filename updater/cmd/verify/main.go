// Verify a signed release artifact and optionally extract it for local QA.
package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/bundle"
	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

func main() {
	publicPath := flag.String("public", "", "release public key JSON")
	manifestPath := flag.String("manifest", "", "signed manifest JSON")
	bundlePath := flag.String("bundle", "", "version ZIP")
	current := flag.String("current", "", "source version")
	extract := flag.String("extract", "", "optional new directory for extraction QA")
	flag.Parse()
	if err := verify(*publicPath, *manifestPath, *bundlePath, *current, *extract); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func verify(publicPath, manifestPath, bundlePath, current, extract string) error {
	publicBytes, err := os.ReadFile(publicPath)
	if err != nil {
		return err
	}
	var record struct {
		KeyID     string `json:"keyId"`
		PublicKey string `json:"publicKey"`
	}
	if err := json.Unmarshal(publicBytes, &record); err != nil {
		return err
	}
	key, err := hex.DecodeString(record.PublicKey)
	if err != nil || len(key) != ed25519.PublicKeySize {
		return errors.New("invalid public key")
	}
	envelopeBytes, err := os.ReadFile(manifestPath)
	if err != nil {
		return err
	}
	var envelope manifest.Envelope
	if err := json.Unmarshal(envelopeBytes, &envelope); err != nil {
		return err
	}
	payload, err := manifest.Verify(envelope, map[string]ed25519.PublicKey{record.KeyID: key}, current, time.Now())
	if err != nil {
		return err
	}
	file, err := os.Open(bundlePath)
	if err != nil {
		return err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return err
	}
	if info.Size() != payload.Bytes {
		return errors.New("bundle size does not match signed manifest")
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return err
	}
	if hex.EncodeToString(hash.Sum(nil)) != payload.SHA256 {
		return errors.New("bundle hash does not match signed manifest")
	}
	if extract != "" {
		if err := os.MkdirAll(filepath.Dir(extract), 0700); err != nil {
			return err
		}
		if err := bundle.Extract(bundlePath, extract, payload.Version); err != nil {
			return err
		}
	}
	fmt.Printf("verified version=%s sha256=%s\n", payload.Version, payload.SHA256)
	return nil
}
