package engine

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCommitOnlyAfterTrial(t *testing.T) {
	store := Store{Root: t.TempDir()}
	state := State{Current: "0.9.0"}
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}
	var err error
	state, err = store.Begin(state, Trial{ID: "tx-1", Version: "0.9.1", SHA256: strings.Repeat("a", 64)})
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Commit(state); err == nil {
		t.Fatal("committed before health trial")
	}
	state, err = store.SetPhase(state, "prepared")
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.SetPhase(state, "trial")
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.Commit(state)
	if err != nil {
		t.Fatal(err)
	}
	if state.Current != "0.9.1" || state.Previous != "0.9.0" || state.Pending != nil {
		t.Fatalf("unexpected state: %+v", state)
	}
	loaded, err := store.Load()
	if err != nil || loaded.Current != state.Current {
		t.Fatalf("loaded %+v: %v", loaded, err)
	}
	state, err = store.RevertCommit(state, Failed{Version: "0.9.1", SHA256: strings.Repeat("a", 64)})
	if err != nil || state.Current != "0.9.0" || state.Failed == nil {
		t.Fatalf("immediate start rollback %+v: %v", state, err)
	}
}

func TestInterruptedTrialRecoversCommittedVersion(t *testing.T) {
	store := Store{Root: t.TempDir()}
	state := State{Current: "0.9.0"}
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}
	var err error
	state, err = store.Begin(state, Trial{ID: "tx-1", Version: "0.9.1", SHA256: strings.Repeat("a", 64)})
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.SetPhase(state, "prepared")
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.SetPhase(state, "trial")
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.Load()
	if err != nil {
		t.Fatal(err)
	}
	state, err = store.Recover(state)
	if err != nil {
		t.Fatal(err)
	}
	if state.Current != "0.9.0" || state.Failed == nil || state.Failed.Version != "0.9.1" {
		t.Fatalf("unexpected recovery: %+v", state)
	}
}

func TestCorruptPrimaryLoadsBackup(t *testing.T) {
	store := Store{Root: t.TempDir()}
	if err := store.Save(State{Current: "0.9.0"}); err != nil {
		t.Fatal(err)
	}
	if err := store.Save(State{Current: "0.9.1", Previous: "0.9.0"}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(store.Root, "update-state.json"), []byte("bad"), 0600); err != nil {
		t.Fatal(err)
	}
	state, err := store.Load()
	if err != nil || state.Current != "0.9.0" {
		t.Fatalf("backup %+v: %v", state, err)
	}
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}
	backup, err := read(store.backupPath())
	if err != nil || backup.Current != "0.9.0" {
		t.Fatalf("recovery copy was lost: %+v %v", backup, err)
	}
}

func TestRejectsUnsafeNames(t *testing.T) {
	store := Store{Root: t.TempDir()}
	for _, name := range []string{"../other", "..", "a/b", ""} {
		if err := store.Save(State{Current: name}); err == nil {
			t.Fatalf("accepted %q", name)
		}
	}
}
