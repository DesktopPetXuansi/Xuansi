// Key generation is a one-time release operation. The private output must be
// stored outside the repository and backed up offline by its owner.
package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	privatePath := flag.String("private", "", "absolute path outside the repository")
	publicPath := flag.String("public", "", "public key JSON path")
	keyID := flag.String("id", "", "stable key identifier")
	flag.Parse()
	if err := generate(*privatePath, *publicPath, *keyID); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func generate(privatePath, publicPath, keyID string) error {
	if !filepath.IsAbs(privatePath) || !filepath.IsAbs(publicPath) || keyID == "" {
		return errors.New("private, public and id are required")
	}
	if err := os.MkdirAll(filepath.Dir(privatePath), 0700); err != nil {
		return err
	}
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return err
	}
	file, err := os.OpenFile(privatePath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return err
	}
	if _, err := file.WriteString(hex.EncodeToString(private) + "\n"); err != nil {
		file.Close()
		return err
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return err
	}
	if err := file.Close(); err != nil {
		return err
	}
	data, err := json.MarshalIndent(struct {
		KeyID     string `json:"keyId"`
		PublicKey string `json:"publicKey"`
	}{KeyID: keyID, PublicKey: hex.EncodeToString(public)}, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(publicPath, append(data, '\n'), 0644)
}
