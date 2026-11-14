// Sign one already-built immutable version bundle with an offline release key.
package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

func main() {
	keyPath := flag.String("key", "", "private key file outside repository")
	keyID := flag.String("id", "", "public release key identifier")
	version := flag.String("version", "", "bundle semantic version")
	minimum := flag.String("min-from", "", "minimum directly supported source version")
	filePath := flag.String("file", "", "built version bundle")
	downloadURL := flag.String("url", "", "published HTTPS artifact URL")
	output := flag.String("output", "", "signed envelope output")
	flag.Parse()
	if err := sign(*keyPath, *keyID, *version, *minimum, *filePath, *downloadURL, *output); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func sign(keyPath, keyID, version, minimum, filePath, downloadURL, output string) error {
	if keyPath == "" || keyID == "" || filePath == "" || output == "" {
		return errors.New("missing signing input")
	}
	if _, err := manifest.CompareVersion(version, minimum); err != nil {
		return err
	}
	u, err := url.Parse(downloadURL)
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil {
		return errors.New("invalid download URL")
	}
	keyText, err := os.ReadFile(keyPath)
	if err != nil {
		return err
	}
	key, err := hex.DecodeString(string(trimSpace(keyText)))
	if err != nil || len(key) != ed25519.PrivateKeySize {
		return errors.New("invalid private key file")
	}
	file, err := os.Open(filePath)
	if err != nil {
		return err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return err
	}
	if info.Size() <= 0 || info.Size() > 8<<30 {
		return errors.New("invalid bundle size")
	}
	digest := sha256.New()
	if _, err := io.Copy(digest, file); err != nil {
		return err
	}
	now := time.Now().UTC()
	payload := manifest.Payload{Format: 1, KeyID: keyID, Version: version, Channel: "STABLE", OS: "windows", Arch: "x64", DistributionType: "VERSION_BUNDLE", URL: downloadURL, SHA256: hex.EncodeToString(digest.Sum(nil)), Bytes: info.Size(), Issued: now.Format(time.RFC3339), Expires: now.Add(30 * 24 * time.Hour).Format(time.RFC3339), MinFrom: minimum, DataFormat: 1}
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	envelope := manifest.Envelope{Payload: base64.StdEncoding.EncodeToString(raw), Signature: hex.EncodeToString(ed25519.Sign(ed25519.PrivateKey(key), raw))}
	encoded, err := json.MarshalIndent(envelope, "", "  ")
	if err != nil {
		return err
	}
	result, err := os.OpenFile(output, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	if _, err := result.Write(append(encoded, '\n')); err != nil {
		result.Close()
		return err
	}
	if err := result.Sync(); err != nil {
		result.Close()
		return err
	}
	return result.Close()
}

func trimSpace(data []byte) []byte {
	for len(data) > 0 && (data[len(data)-1] == '\n' || data[len(data)-1] == '\r' || data[len(data)-1] == ' ') {
		data = data[:len(data)-1]
	}
	return data
}
