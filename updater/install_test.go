//go:build windows

package main

import (
	"archive/zip"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/DesktopPetXuansi/Xuansi/updater/engine"
	"github.com/DesktopPetXuansi/Xuansi/updater/manifest"
)

const fakePython = `package main
import (
 "encoding/json"
 "fmt"
 "os"
 "strings"
)
func main() {
 for _, arg := range os.Args[1:] {
  if arg == "--update-health-check" {
   if os.Getenv("FAIL_TRIAL") == "1" { os.Exit(2) }
   version, _ := os.ReadFile("VERSION")
   reply, _ := json.Marshal(map[string]string{"nonce":os.Getenv("XUANSI_UPDATE_TRIAL_NONCE"), "version":strings.TrimSpace(string(version))})
   fmt.Println(string(reply))
   return
  }
 }
}
`

func fakeExecutable(t *testing.T) []byte {
	t.Helper()
	dir := t.TempDir()
	source := filepath.Join(dir, "main.go")
	program := filepath.Join(dir, "python.exe")
	if err := os.WriteFile(source, []byte(fakePython), 0600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("go", "build", "-o", program, source)
	cmd.Env = append(os.Environ(), "GO111MODULE=off")
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("fake Python build: %v %s", err, output)
	}
	data, err := os.ReadFile(program)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func fixture(t *testing.T) (string, engine.Store, engine.State, manifest.Payload, string) {
	t.Helper()
	root := t.TempDir()
	old := filepath.Join(root, "versions", "0.9.0", "runtime", "python")
	if err := os.MkdirAll(old, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(root, "data"), 0700); err != nil {
		t.Fatal(err)
	}
	program := fakeExecutable(t)
	if err := os.WriteFile(filepath.Join(old, "pythonw.exe"), program, 0600); err != nil {
		t.Fatal(err)
	}
	archive := filepath.Join(root, "candidate.zip")
	file, err := os.Create(archive)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(file)
	entries := map[string][]byte{
		"VERSION":                    []byte("0.9.1\n"),
		"pet/__main__.py":            []byte("pass\n"),
		"runtime/python/python.exe":  program,
		"runtime/python/pythonw.exe": program,
	}
	for name, data := range entries {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	store := engine.Store{Root: filepath.Join(root, "update")}
	state := engine.State{Current: "0.9.0"}
	if err := store.Save(state); err != nil {
		t.Fatal(err)
	}
	candidate := manifest.Payload{Version: "0.9.1", SHA256: strings.Repeat("a", 64)}
	return root, store, state, candidate, archive
}

func TestInstallCandidateCommitsAfterHealth(t *testing.T) {
	root, store, state, candidate, archive := fixture(t)
	if err := installCandidate(root, store, state, candidate, archive); err != nil {
		t.Fatal(err)
	}
	committed, err := store.Load()
	if err != nil || committed.Current != "0.9.1" || committed.Previous != "0.9.0" {
		t.Fatalf("commit %+v: %v", committed, err)
	}
}

func TestInstallCandidateRestartsOldAfterTrialFailure(t *testing.T) {
	root, store, state, candidate, archive := fixture(t)
	t.Setenv("FAIL_TRIAL", "1")
	if err := installCandidate(root, store, state, candidate, archive); err == nil {
		t.Fatal("accepted failed trial")
	}
	recovered, err := store.Load()
	if err != nil || recovered.Current != "0.9.0" || recovered.Failed == nil || recovered.Failed.Version != "0.9.1" {
		t.Fatalf("recovery %+v: %v", recovered, err)
	}
}
