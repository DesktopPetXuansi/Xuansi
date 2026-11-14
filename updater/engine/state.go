package engine

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

// State is the durable selection made by the launcher. Current changes only
// after the candidate has completed its read-only health trial.
type State struct {
	Current  string  `json:"current"`
	Previous string  `json:"previous,omitempty"`
	Pending  *Trial  `json:"pending,omitempty"`
	Failed   *Failed `json:"failed,omitempty"`
}

type Trial struct {
	ID      string `json:"id"`
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
	Phase   string `json:"phase"`
}

type Failed struct {
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
}

var (
	namePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`)
	hashPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

func valid(s State) error {
	if !namePattern.MatchString(s.Current) || s.Current == "." || s.Current == ".." {
		return errors.New("invalid current version")
	}
	if s.Previous != "" && (!namePattern.MatchString(s.Previous) || s.Previous == s.Current) {
		return errors.New("invalid previous version")
	}
	if p := s.Pending; p != nil {
		if !namePattern.MatchString(p.ID) || !namePattern.MatchString(p.Version) ||
			p.Version == s.Current || !hashPattern.MatchString(p.SHA256) ||
			(p.Phase != "preparing" && p.Phase != "prepared" && p.Phase != "trial" && p.Phase != "rolling_back") {
			return errors.New("invalid pending transaction")
		}
	}
	if f := s.Failed; f != nil && (!namePattern.MatchString(f.Version) || !hashPattern.MatchString(f.SHA256)) {
		return errors.New("invalid failed version")
	}
	return nil
}

// Store must be used by one launcher process at a time. The caller owns the
// process-wide lock; State itself never resolves untrusted paths.
type Store struct{ Root string }

func (s Store) statePath() string  { return filepath.Join(s.Root, "update-state.json") }
func (s Store) backupPath() string { return filepath.Join(s.Root, "update-state.previous.json") }

func read(path string) (State, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return State{}, err
	}
	var state State
	if err := json.Unmarshal(data, &state); err != nil {
		return State{}, err
	}
	if err := valid(state); err != nil {
		return State{}, err
	}
	return state, nil
}

func (s Store) Load() (State, error) {
	state, err := read(s.statePath())
	if err == nil {
		return state, nil
	}
	backup, backupErr := read(s.backupPath())
	if backupErr == nil {
		return backup, nil
	}
	return State{}, fmt.Errorf("update state unavailable: primary: %w; backup: %v", err, backupErr)
}

func (s Store) Save(state State) error {
	if err := valid(state); err != nil {
		return err
	}
	if err := os.MkdirAll(s.Root, 0700); err != nil {
		return err
	}
	data, err := json.Marshal(state)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(s.Root, ".update-state-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err = tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err = tmp.Close(); err != nil {
		return err
	}
	if _, err = os.Stat(s.statePath()); err == nil {
		if _, readErr := read(s.statePath()); readErr != nil {
			// Keep the valid backup if the primary was damaged after the last
			// commit. Never rotate damaged bytes over the recovery copy.
			if err = os.Remove(s.statePath()); err != nil {
				return err
			}
		} else {
			// A crash after this rename still leaves a valid state for Load.
			if err = os.Remove(s.backupPath()); err != nil && !errors.Is(err, os.ErrNotExist) {
				return err
			}
			if err = os.Rename(s.statePath(), s.backupPath()); err != nil {
				return err
			}
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return os.Rename(tmp.Name(), s.statePath())
}

func (s Store) Begin(current State, trial Trial) (State, error) {
	if current.Pending != nil {
		return State{}, errors.New("transaction already active")
	}
	trial.Phase = "preparing"
	current.Pending = &trial
	return current, s.Save(current)
}

func (s Store) SetPhase(current State, phase string) (State, error) {
	if current.Pending == nil {
		return State{}, errors.New("no active transaction")
	}
	allowed := map[string]string{"preparing": "prepared", "prepared": "trial", "trial": "rolling_back"}
	if allowed[current.Pending.Phase] != phase {
		return State{}, errors.New("invalid phase transition")
	}
	copy := *current.Pending
	copy.Phase = phase
	current.Pending = &copy
	return current, s.Save(current)
}

func (s Store) Commit(current State) (State, error) {
	if current.Pending == nil || current.Pending.Phase != "trial" {
		return State{}, errors.New("trial not active")
	}
	old := current.Current
	current.Current = current.Pending.Version
	current.Previous = old
	current.Pending = nil
	return current, s.Save(current)
}

// Recover chooses the last committed version for any interrupted trial. It
// retains the rejected artifact identity to prevent an automatic retry loop.
func (s Store) Recover(current State) (State, error) {
	if current.Pending == nil {
		return current, nil
	}
	current.Failed = &Failed{Version: current.Pending.Version, SHA256: current.Pending.SHA256}
	current.Pending = nil
	return current, s.Save(current)
}

// RevertCommit is only used when starting the new process fails immediately,
// before the new application can write business data.
func (s Store) RevertCommit(current State, failed Failed) (State, error) {
	if current.Pending != nil || current.Previous == "" || current.Current != failed.Version {
		return State{}, errors.New("cannot revert committed version")
	}
	current.Current = current.Previous
	current.Previous = ""
	current.Failed = &failed
	return current, s.Save(current)
}
