package bundle

import (
	"archive/zip"
	"os"
	"path/filepath"
	"testing"
)

func makeBundle(t *testing.T, files map[string]string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "bundle.zip")
	file, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	writer := zip.NewWriter(file)
	for name, content := range files {
		entry, err := writer.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write([]byte(content)); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestExtractChecksRequiredFiles(t *testing.T) {
	archive := makeBundle(t, map[string]string{
		"VERSION": "0.9.1\n", "pet/__main__.py": "pass", "runtime/python/python.exe": "stub", "runtime/python/pythonw.exe": "stub",
	})
	destination := filepath.Join(t.TempDir(), "0.9.1")
	if err := Extract(archive, destination, "0.9.1"); err != nil {
		t.Fatal(err)
	}
	if err := Extract(archive, destination, "0.9.1"); err == nil {
		t.Fatal("reused existing candidate directory")
	}
}

func TestExtractRejectsTraversal(t *testing.T) {
	archive := makeBundle(t, map[string]string{"VERSION": "0.9.1", "a/../../outside": "bad"})
	root := t.TempDir()
	if err := Extract(archive, filepath.Join(root, "candidate"), "0.9.1"); err == nil {
		t.Fatal("accepted traversal")
	}
	if _, err := os.Stat(filepath.Join(root, "outside")); !os.IsNotExist(err) {
		t.Fatalf("wrote outside destination: %v", err)
	}
}
