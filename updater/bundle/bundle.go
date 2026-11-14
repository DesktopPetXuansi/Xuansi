package bundle

import (
	"archive/zip"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
)

// Extract creates a version at its final path. Python environments must not
// be moved after preparation because their launch paths can be absolute.
func Extract(archive, destination, version string) error {
	if _, err := os.Lstat(destination); err == nil {
		return errors.New("candidate directory already exists")
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	reader, err := zip.OpenReader(archive)
	if err != nil {
		return err
	}
	defer reader.Close()
	if len(reader.File) == 0 || len(reader.File) > 100000 {
		return errors.New("invalid bundle file count")
	}
	if err := os.Mkdir(destination, 0700); err != nil {
		return err
	}
	seen := map[string]bool{}
	var total uint64
	for _, item := range reader.File {
		name := item.Name
		if name == "" || strings.ContainsAny(name, "\\:\x00") || strings.HasPrefix(name, "/") {
			return errors.New("unsafe bundle path")
		}
		for _, component := range strings.Split(name, "/") {
			if component == "." || component == ".." {
				return errors.New("unsafe bundle path")
			}
		}
		clean := filepath.Clean(filepath.FromSlash(name))
		if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(os.PathSeparator)) {
			return errors.New("unsafe bundle path")
		}
		key := strings.ToLower(clean)
		if seen[key] {
			return errors.New("duplicate bundle path")
		}
		seen[key] = true
		mode := item.Mode()
		if mode&os.ModeSymlink != 0 || (!mode.IsRegular() && !mode.IsDir()) {
			return errors.New("bundle contains special file")
		}
		total += item.UncompressedSize64
		if total > 8<<30 {
			return errors.New("bundle expands beyond limit")
		}
		target := filepath.Join(destination, clean)
		if mode.IsDir() {
			if err := os.MkdirAll(target, 0700); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0700); err != nil {
			return err
		}
		input, err := item.Open()
		if err != nil {
			return err
		}
		output, err := os.OpenFile(target, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if err != nil {
			input.Close()
			return err
		}
		written, copyErr := io.CopyN(output, input, int64(item.UncompressedSize64)+1)
		if copyErr == io.EOF {
			copyErr = nil
		}
		syncErr := output.Sync()
		closeErr := output.Close()
		input.Close()
		if copyErr != nil || syncErr != nil || closeErr != nil || written != int64(item.UncompressedSize64) {
			return fmt.Errorf("bundle entry failed verification: %s", clean)
		}
	}
	actual, err := os.ReadFile(filepath.Join(destination, "VERSION"))
	if err != nil || strings.TrimSpace(string(actual)) != version {
		return errors.New("bundle version mismatch")
	}
	for _, name := range []string{"pet/__main__.py", "runtime/python/python.exe", "runtime/python/pythonw.exe"} {
		info, err := os.Lstat(filepath.Join(destination, filepath.FromSlash(name)))
		if err != nil || !info.Mode().IsRegular() {
			return fmt.Errorf("bundle missing %s", name)
		}
	}
	return nil
}
