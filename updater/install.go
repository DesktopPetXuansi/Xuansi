package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/DesktopPetXuansi/Xuansi/updater/bundle"
	"github.com/DesktopPetXuansi/Xuansi/updater/engine"
	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

func waitForAppExit(root string) error {
	lock := filepath.Join(root, "shared", "data", "app.lock")
	deadline := time.Now().Add(45 * time.Second)
	for {
		_, err := os.Lstat(lock)
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		if err != nil {
			return err
		}
		if time.Now().After(deadline) {
			return errors.New("desktop pet is still running")
		}
		time.Sleep(250 * time.Millisecond)
	}
}

func installCandidate(root string, store engine.Store, state engine.State, candidate manifest.Payload, archive string) error {
	if state.Pending != nil {
		return errors.New("another update transaction is active")
	}
	if state.Failed != nil && state.Failed.Version == candidate.Version && state.Failed.SHA256 == candidate.SHA256 {
		return errors.New("this update failed previously and requires manual repair")
	}
	versions := filepath.Join(root, "versions")
	if info, err := os.Lstat(versions); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("version directory is unavailable or unsafe")
	}
	if info, err := os.Lstat(filepath.Join(root, "shared", "data")); err != nil || !info.IsDir() {
		return errors.New("shared user data has not been prepared")
	}
	if err := waitForAppExit(root); err != nil {
		return err
	}
	transaction := engine.Trial{ID: fmt.Sprintf("tx-%d", time.Now().UnixNano()), Version: candidate.Version, SHA256: candidate.SHA256}
	state, err := store.Begin(state, transaction)
	if err != nil {
		return err
	}
	destination := filepath.Join(versions, candidate.Version)
	if err := bundle.Extract(archive, destination, candidate.Version); err != nil {
		return recoverAndStart(root, store, err)
	}
	state, err = store.SetPhase(state, "prepared")
	if err != nil {
		return recoverAndStart(root, store, err)
	}
	state, err = store.SetPhase(state, "trial")
	if err != nil {
		return recoverAndStart(root, store, err)
	}
	if err := trialCandidate(root, candidate.Version); err != nil {
		return recoverAndStart(root, store, fmt.Errorf("candidate failed health trial: %w", err))
	}
	state, err = store.Commit(state)
	if err != nil {
		return recoverAndStart(root, store, err)
	}
	if err := start(root, state, nil); err != nil {
		state, revertErr := store.RevertCommit(state, engine.Failed{Version: candidate.Version, SHA256: candidate.SHA256})
		if revertErr != nil {
			return errors.Join(err, revertErr)
		}
		return errors.Join(err, start(root, state, nil))
	}
	return nil
}

func recoverAndStart(root string, store engine.Store, cause error) error {
	current, err := store.Load()
	if err != nil {
		return errors.Join(cause, err)
	}
	if current.Pending != nil {
		current, err = store.Recover(current)
		if err != nil {
			return errors.Join(cause, err)
		}
	}
	return errors.Join(cause, start(root, current, nil))
}
