package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

type healthReply struct {
	Nonce   string `json:"nonce"`
	Version string `json:"version"`
}

// trialCandidate runs a separate read-only process. It never selects the
// candidate; the caller must persist a committed state after this succeeds.
func trialCandidate(root, version string) error {
	path, err := versionPath(root, version)
	if err != nil {
		return err
	}
	python, err := pythonPath(path, false)
	if err != nil {
		return err
	}
	nonceBytes := make([]byte, 32)
	if _, err := rand.Read(nonceBytes); err != nil {
		return err
	}
	nonce := hex.EncodeToString(nonceBytes)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, python, "-B", "-m", "pet", "--update-health-check")
	cmd.Dir = path
	cmd.Env = append(os.Environ(),
		"XUANSI_WRITABLE_ROOT="+root,
		"XUANSI_VERSION_RUNTIME_ROOT="+filepath.Join(path, "runtime"),
		"XUANSI_UPDATE_TRIAL_NONCE="+nonce,
	)
	output, err := cmd.Output()
	if ctx.Err() != nil {
		return errors.New("candidate health trial timed out")
	}
	if err != nil {
		return fmt.Errorf("candidate health trial failed: %w", err)
	}
	if len(output) > 4096 {
		return errors.New("candidate health reply too large")
	}
	var reply healthReply
	if err := json.Unmarshal([]byte(strings.TrimSpace(string(output))), &reply); err != nil {
		return err
	}
	if reply.Nonce != nonce || reply.Version != version {
		return errors.New("candidate health reply mismatch")
	}
	return nil
}
