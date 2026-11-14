package download

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
)

// Fetch retains a partial file after cancellation. It only publishes a
// complete file after size and SHA-256 verification.
func Fetch(ctx context.Context, client *http.Client, source, destination string, size int64, expectedHash string) error {
	if size <= 0 || size > 8<<30 || len(expectedHash) != 64 {
		return errors.New("invalid expected artifact")
	}
	if okay, err := verify(destination, size, expectedHash); err != nil {
		return err
	} else if okay {
		return nil
	}
	part := destination + ".part"
	metadata := destination + ".etag"
	if err := regularOrMissing(part); err != nil {
		return err
	}
	if err := regularOrMissing(metadata); err != nil {
		return err
	}
	start := int64(0)
	if info, err := os.Stat(part); err == nil {
		start = info.Size()
		if start >= size {
			os.Remove(part)
			start = 0
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, source, nil)
	if err != nil {
		return err
	}
	if start > 0 {
		request.Header.Set("Range", fmt.Sprintf("bytes=%d-", start))
		if tag, err := os.ReadFile(metadata); err == nil && validETag(string(tag)) {
			request.Header.Set("If-Range", string(tag))
		}
	}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	appendFile := false
	if start > 0 && response.StatusCode == http.StatusPartialContent {
		prefix := fmt.Sprintf("bytes %d-", start)
		if !strings.HasPrefix(response.Header.Get("Content-Range"), prefix) || !strings.HasSuffix(response.Header.Get("Content-Range"), "/"+strconv.FormatInt(size, 10)) {
			return errors.New("resume range does not match artifact")
		}
		appendFile = true
	} else if response.StatusCode != http.StatusOK {
		return fmt.Errorf("download service returned %d", response.StatusCode)
	}
	flags := os.O_CREATE | os.O_WRONLY
	if appendFile {
		flags |= os.O_APPEND
	} else {
		flags |= os.O_TRUNC
		start = 0
	}
	file, err := os.OpenFile(part, flags, 0600)
	if err != nil {
		return err
	}
	copyCount, copyErr := io.Copy(file, io.LimitReader(response.Body, size-start+1))
	syncErr := file.Sync()
	closeErr := file.Close()
	if copyErr != nil {
		return copyErr
	}
	if syncErr != nil {
		return syncErr
	}
	if closeErr != nil {
		return closeErr
	}
	if tag := response.Header.Get("ETag"); validETag(tag) {
		_ = os.WriteFile(metadata, []byte(tag), 0600)
	}
	if copyCount+start != size {
		return errors.New("download size mismatch")
	}
	if okay, err := verify(part, size, expectedHash); err != nil || !okay {
		_ = os.Remove(part)
		return errors.New("download hash mismatch")
	}
	if err := os.Remove(destination); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err := os.Rename(part, destination); err != nil {
		return err
	}
	_ = os.Remove(metadata)
	return nil
}

func validETag(value string) bool {
	return len(value) > 1 && len(value) < 256 && !strings.HasPrefix(value, "W/") &&
		!strings.ContainsAny(value, "\r\n") && value[0] == '"' && value[len(value)-1] == '"'
}

func regularOrMissing(path string) error {
	info, err := os.Lstat(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	if !info.Mode().IsRegular() {
		return errors.New("download cache is not a regular file")
	}
	return nil
}

func verify(path string, size int64, expectedHash string) (bool, error) {
	if err := regularOrMissing(path); err != nil {
		return false, err
	}
	file, err := os.Open(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return false, err
	}
	if info.Size() != size {
		return false, nil
	}
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return false, err
	}
	return hex.EncodeToString(hash.Sum(nil)) == expectedHash, nil
}
