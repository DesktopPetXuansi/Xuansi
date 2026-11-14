// Xuansi's stable entry point. It contains no Python or Qt dependency and
// selects only versions recorded by the local update transaction.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/download"
	"github.com/DesktopPetXuansi/Xuansi/updater/engine"
)

func versionPath(root, version string) (string, error) {
	base := filepath.Join(root, "versions")
	path := filepath.Join(base, version)
	if filepath.Base(path) != version || version == "." || version == ".." {
		return "", errors.New("unsafe version path")
	}
	for _, component := range []string{base, path} {
		info, err := os.Lstat(component)
		if err != nil {
			return "", err
		}
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return "", errors.New("version path is not a real directory")
		}
	}
	return path, nil
}

func start(root string, state engine.State, args []string) error {
	path, err := versionPath(root, state.Current)
	if err != nil {
		return err
	}
	python := filepath.Join(path, "runtime", "python", "pythonw.exe")
	if info, err := os.Lstat(python); err != nil || !info.Mode().IsRegular() {
		return fmt.Errorf("committed version missing Python: %v", err)
	}
	cmd := exec.Command(python, append([]string{"-B", "-m", "pet"}, args...)...)
	cmd.Dir = path
	cmd.Env = append(os.Environ(),
		"XUANSI_WRITABLE_ROOT="+filepath.Join(root, "shared"),
		"XUANSI_VERSION_RUNTIME_ROOT="+filepath.Join(path, "runtime"),
	)
	return cmd.Start()
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "玄司无法启动：", err)
		os.Exit(1)
	}
}

func run() error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	root := filepath.Dir(executable)
	identity := sha256.Sum256([]byte(strings.ToLower(root)))
	mutex, err := acquireMutex("Local\\XuansiUpdater-" + hex.EncodeToString(identity[:16]))
	if err != nil {
		return err
	}
	defer mutex.Close()
	store := engine.Store{Root: filepath.Join(root, "update")}
	state, err := store.Load()
	if err != nil {
		return err
	}
	if state.Pending != nil {
		state, err = store.Recover(state)
		if err != nil {
			return err
		}
	}
	updateCommand := (len(os.Args) == 2 && (os.Args[1] == "--check-update" || os.Args[1] == "--download-update")) ||
		(len(os.Args) == 4 && os.Args[1] == "--apply-update")
	if updateCommand {
		keys, err := trustedKeys()
		if err != nil {
			return err
		}
		client := &http.Client{Timeout: 12 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse }}
		candidate, err := checkUpdates(client, releaseEndpoint, state.Current, keys, time.Now())
		if err != nil {
			return err
		}
		if os.Args[1] == "--apply-update" && (candidate == nil || candidate.Version != os.Args[2] || candidate.SHA256 != os.Args[3]) {
			return errors.New("selected update has changed or was withdrawn")
		}
		if candidate != nil && os.Args[1] != "--check-update" {
			cache := filepath.Join(root, "update", "downloads")
			if err := os.MkdirAll(cache, 0700); err != nil {
				return err
			}
			artifact := filepath.Join(cache, candidate.SHA256+".zip")
			transfer := &http.Client{CheckRedirect: func(request *http.Request, via []*http.Request) error {
				if request.URL.Scheme != "https" || len(via) > 5 {
					return errors.New("unsafe download redirect")
				}
				return nil
			}}
			if err := download.Fetch(context.Background(), transfer, candidate.URL, artifact, candidate.Bytes, candidate.SHA256); err != nil {
				return err
			}
			if os.Args[1] == "--apply-update" {
				return installCandidate(root, store, state, *candidate, artifact)
			}
		}
		return json.NewEncoder(os.Stdout).Encode(candidate)
	}
	return start(root, state, os.Args[1:])
}
