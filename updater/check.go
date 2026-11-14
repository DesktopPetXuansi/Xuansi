package main

import (
	"crypto/ed25519"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

const releaseEndpoint = "https://xuansi.kukude.top/api/v1/client/releases?channel=STABLE&os=windows&arch=x64"

//go:embed release-public-key.json
var releasePublicKeyJSON []byte

type releaseListing struct {
	Data []struct {
		Artifacts []struct {
			DistributionType string `json:"distributionType"`
			UpdateManifest   string `json:"updateManifest"`
			UpdateSignature  string `json:"updateSignature"`
		} `json:"artifacts"`
	} `json:"data"`
}

func trustedKeys() (map[string]ed25519.PublicKey, error) {
	var record struct {
		KeyID     string `json:"keyId"`
		PublicKey string `json:"publicKey"`
	}
	if err := json.Unmarshal(releasePublicKeyJSON, &record); err != nil {
		return nil, err
	}
	key, err := hex.DecodeString(record.PublicKey)
	if err != nil || len(key) != ed25519.PublicKeySize || record.KeyID == "" {
		return nil, errors.New("release trust key is not configured")
	}
	return map[string]ed25519.PublicKey{record.KeyID: key}, nil
}

func checkUpdates(client *http.Client, endpoint, current string, keys map[string]ed25519.PublicKey, now time.Time) (*manifest.Payload, error) {
	request, err := http.NewRequest(http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	response, err := client.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("release service returned %d", response.StatusCode)
	}
	limited := io.LimitReader(response.Body, 1<<20+1)
	body, err := io.ReadAll(limited)
	if err != nil || len(body) > 1<<20 {
		return nil, errors.New("release response too large or unreadable")
	}
	var listing releaseListing
	if err := json.Unmarshal(body, &listing); err != nil {
		return nil, err
	}
	var best *manifest.Payload
	var invalid error
	for _, release := range listing.Data {
		for _, artifact := range release.Artifacts {
			if artifact.DistributionType != "VERSION_BUNDLE" {
				continue
			}
			value, err := manifest.Verify(manifest.Envelope{Payload: artifact.UpdateManifest, Signature: artifact.UpdateSignature}, keys, current, now)
			if err != nil {
				if errors.Is(err, manifest.ErrNotNewer) {
					continue
				}
				invalid = err
				continue
			}
			if best == nil {
				best = &value
				continue
			}
			greater, _ := manifest.CompareVersion(value.Version, best.Version)
			if greater > 0 {
				best = &value
			}
		}
	}
	if best == nil && invalid != nil {
		return nil, invalid
	}
	return best, nil
}
