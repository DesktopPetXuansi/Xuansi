package manifest

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Envelope signs the exact JSON bytes in Payload. The server is only a
// transport; its database fields are not trusted for installing an update.
type Envelope struct {
	Payload   string `json:"payload"`
	Signature string `json:"signature"`
}

type Payload struct {
	Format           int    `json:"format"`
	KeyID            string `json:"keyId"`
	Version          string `json:"version"`
	Channel          string `json:"channel"`
	OS               string `json:"os"`
	Arch             string `json:"arch"`
	DistributionType string `json:"distributionType"`
	URL              string `json:"url"`
	SHA256           string `json:"sha256"`
	Bytes            int64  `json:"bytes"`
	Issued           string `json:"issued"`
	Expires          string `json:"expires"`
	MinFrom          string `json:"minFrom"`
	DataFormat       int    `json:"dataFormat"`
}

var versionPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`)
var hashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
var ErrNotNewer = errors.New("update is not newer")

func CompareVersion(a, b string) (int, error) {
	if !versionPattern.MatchString(a) || !versionPattern.MatchString(b) {
		return 0, errors.New("invalid version")
	}
	aa, bb := strings.Split(a, "."), strings.Split(b, ".")
	for i := range aa {
		av, ae := strconv.ParseUint(aa[i], 10, 32)
		bv, be := strconv.ParseUint(bb[i], 10, 32)
		if ae != nil || be != nil {
			return 0, errors.New("version component too large")
		}
		if av < bv {
			return -1, nil
		}
		if av > bv {
			return 1, nil
		}
	}
	return 0, nil
}

func Verify(envelope Envelope, keys map[string]ed25519.PublicKey, current string, now time.Time) (Payload, error) {
	raw, err := base64.StdEncoding.Strict().DecodeString(envelope.Payload)
	if err != nil || len(raw) == 0 || len(raw) > 8192 {
		return Payload{}, errors.New("invalid signed payload")
	}
	signature, err := hex.DecodeString(envelope.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize {
		return Payload{}, errors.New("invalid signature encoding")
	}
	var value Payload
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return Payload{}, err
	}
	if err := decoder.Decode(new(any)); err != io.EOF {
		return Payload{}, errors.New("trailing payload data")
	}
	key := keys[value.KeyID]
	if len(key) != ed25519.PublicKeySize || !ed25519.Verify(key, raw, signature) {
		return Payload{}, errors.New("update signature is not trusted")
	}
	if value.Format != 1 || value.Channel != "STABLE" || value.OS != "windows" || value.Arch != "x64" || value.DistributionType != "VERSION_BUNDLE" || value.DataFormat != 1 {
		return Payload{}, errors.New("incompatible update artifact")
	}
	if !hashPattern.MatchString(value.SHA256) || value.Bytes <= 0 || value.Bytes > 8<<30 {
		return Payload{}, errors.New("invalid artifact size or hash")
	}
	u, err := url.Parse(value.URL)
	if err != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.Fragment != "" {
		return Payload{}, errors.New("invalid download URL")
	}
	expires, err := time.Parse(time.RFC3339, value.Expires)
	if err != nil || !now.Before(expires) || expires.Sub(now) > 180*24*time.Hour {
		return Payload{}, errors.New("update manifest expired or clock invalid")
	}
	issued, err := time.Parse(time.RFC3339, value.Issued)
	if err != nil || issued.After(now.Add(5*time.Minute)) || now.Sub(issued) > 30*24*time.Hour || expires.Sub(issued) > 30*24*time.Hour {
		return Payload{}, errors.New("update manifest issuance is invalid")
	}
	newer, err := CompareVersion(value.Version, current)
	if err != nil {
		return Payload{}, err
	}
	if newer <= 0 {
		return Payload{}, ErrNotNewer
	}
	minimum, err := CompareVersion(current, value.MinFrom)
	if err != nil || minimum < 0 {
		return Payload{}, errors.New("bridge version required")
	}
	return value, nil
}
