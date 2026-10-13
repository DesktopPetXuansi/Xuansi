package resource

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	_ "golang.org/x/image/webp"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	_ "image/png"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
	"unicode"
)

type File struct {
	Path   string `json:"path"`
	Bytes  int64  `json:"bytes"`
	SHA256 string `json:"sha256"`
}
type Dependency struct {
	ResourceID string `json:"resourceId"`
	VersionID  string `json:"resourceVersionId"`
	Kind       string `json:"kind"`
	Relation   string `json:"relation"`
}
type Capabilities struct {
	Parameters  map[string]string `json:"parameters"`
	Motions     []string          `json:"motions"`
	Expressions []string          `json:"expressions"`
}
type Manifest struct {
	SchemaVersion        int           `json:"schemaVersion"`
	ResourceID           string        `json:"resourceId"`
	ResourceVersionID    string        `json:"resourceVersionId"`
	Kind                 string        `json:"kind"`
	Version              string        `json:"version"`
	Entrypoint           string        `json:"entrypoint"`
	MinimumClientVersion string        `json:"minimumClientVersion"`
	Files                []File        `json:"files"`
	Dependencies         []Dependency  `json:"dependencies"`
	Capabilities         *Capabilities `json:"capabilities,omitempty"`
}
type Package struct {
	Path     string
	Bytes    int64
	SHA256   string
	Manifest Manifest
}

const MaxExpanded = int64(512 << 20)

// SafePath 同时限制 Windows 和 Unix 名称，防止客户端安装时产生不同解释。
func SafePath(s string) bool {
	if s == "" || len(s) > 240 || strings.EqualFold(s, "installed-manifest.json") || strings.ContainsAny(s, "\\:\x00<>\"|?*") || strings.HasPrefix(s, "/") || path.Clean(s) != s {
		return false
	}
	for _, p := range strings.Split(s, "/") {
		if p == "." || p == ".." || strings.HasSuffix(p, ".") || strings.HasSuffix(p, " ") {
			return false
		}
		for _, r := range p {
			if unicode.IsControl(r) {
				return false
			}
		}
		stem := strings.ToUpper(strings.Split(p, ".")[0])
		if stem == "CON" || stem == "PRN" || stem == "AUX" || stem == "NUL" || len(stem) == 4 && (strings.HasPrefix(stem, "COM") || strings.HasPrefix(stem, "LPT")) && stem[3] >= '0' && stem[3] <= '9' {
			return false
		}
	}
	switch strings.ToLower(path.Ext(s)) {
	case ".json", ".moc3", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".wav", ".mp3", ".txt":
		return true
	}
	return false
}

// BuildPackage 从一次读取的受控副本重建 ZIP，发布包不再次读取隔离对象。
func BuildPackage(input, kind, entry, rid, vid, version, minClient string) (Package, error) {
	result := Package{Manifest: Manifest{SchemaVersion: 1, ResourceID: rid, ResourceVersionID: vid, Kind: kind, Version: version, MinimumClientVersion: minClient, Files: []File{}, Dependencies: []Dependency{}}}
	files := map[string][]byte{}
	var total int64
	add := func(name string, reader io.Reader, size int64) error {
		if !SafePath(name) {
			return fmt.Errorf("非法路径或类型：%s", name)
		}
		if _, ok := files[strings.ToLower(name)]; ok {
			return fmt.Errorf("路径大小写冲突：%s", name)
		}
		if size > MaxExpanded || size < 0 || total+size > MaxExpanded {
			return fmt.Errorf("解压容量超过限制")
		}
		b, e := io.ReadAll(io.LimitReader(reader, MaxExpanded-total+1))
		if e != nil {
			return e
		}
		total += int64(len(b))
		if total > MaxExpanded {
			return fmt.Errorf("解压容量超过限制")
		}
		files[name] = b
		return nil
	}
	if strings.EqualFold(filepath.Ext(input), ".zip") || kind == "MODEL" {
		z, e := zip.OpenReader(input)
		if e != nil {
			return result, fmt.Errorf("ZIP 无效：%w", e)
		}
		defer z.Close()
		if len(z.File) > 2048 {
			return result, fmt.Errorf("文件数量超过限制")
		}
		seen := map[string]bool{}
		for _, f := range z.File {
			if f.FileInfo().IsDir() {
				continue
			}
			if f.Mode()&os.ModeSymlink != 0 || f.Mode()&os.ModeType != 0 {
				return result, fmt.Errorf("禁止链接或特殊文件")
			}
			key := strings.ToLower(f.Name)
			if seen[key] {
				return result, fmt.Errorf("重复路径")
			}
			seen[key] = true
			if f.UncompressedSize64 > uint64(MaxExpanded) || f.CompressedSize64 > 0 && f.UncompressedSize64/f.CompressedSize64 > 200 {
				return result, fmt.Errorf("压缩比超限")
			}
			r, e := f.Open()
			if e != nil {
				return result, e
			}
			e = add(f.Name, r, int64(f.UncompressedSize64))
			_ = r.Close()
			if e != nil {
				return result, e
			}
		}
	} else {
		if entry == "" {
			entry = filepath.Base(input)
		}
		r, e := os.Open(input)
		if e != nil {
			return result, e
		}
		info, e := r.Stat()
		if e != nil {
			_ = r.Close()
			return result, e
		}
		e = add(entry, r, info.Size())
		_ = r.Close()
		if e != nil {
			return result, e
		}
	}
	if len(files) == 0 {
		return result, fmt.Errorf("空资源包")
	}
	if kind == "MODEL" {
		if entry == "" {
			for name := range files {
				if strings.HasSuffix(name, ".model3.json") {
					if entry != "" {
						return result, fmt.Errorf("多个模型入口，请明确选择")
					}
					entry = name
				}
			}
		}
		if !strings.HasSuffix(entry, ".model3.json") {
			return result, fmt.Errorf("缺少 model3.json")
		}
		if e := validateModel(files, entry, &result.Manifest); e != nil {
			return result, e
		}
	} else {
		if _, ok := files[entry]; !ok {
			return result, fmt.Errorf("入口不存在")
		}
		if e := validateSingle(kind, entry, files[entry]); e != nil {
			return result, e
		}
	}
	// 逐个图片检查解码尺寸，避免将解压限制误当作像素限制。
	for name, b := range files {
		switch strings.ToLower(path.Ext(name)) {
		case ".png", ".jpg", ".jpeg", ".gif", ".webp":
			if strings.HasSuffix(strings.ToLower(name), ".gif") {
				if e := validateGIF(b); e != nil {
					return result, e
				}
			}
			cfg, _, e := image.DecodeConfig(bytes.NewReader(b))
			if e != nil || cfg.Width <= 0 || cfg.Height <= 0 || int64(cfg.Width)*int64(cfg.Height) > 32_000_000 {
				return result, fmt.Errorf("图片尺寸或格式无效：%s", name)
			}
		}
	}
	result.Manifest.Entrypoint = entry
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	out, e := os.CreateTemp("", "xuansi-package-*.zip")
	if e != nil {
		return result, e
	}
	result.Path = out.Name()
	success := false
	defer func() {
		_ = out.Close()
		if !success {
			_ = os.Remove(out.Name())
		}
	}()
	digest := sha256.New()
	z := zip.NewWriter(io.MultiWriter(out, digest))
	for _, name := range names {
		b := files[name]
		hash := sha256.Sum256(b)
		result.Manifest.Files = append(result.Manifest.Files, File{name, int64(len(b)), hex.EncodeToString(hash[:])})
		h := &zip.FileHeader{Name: name, Method: zip.Deflate}
		h.SetMode(0644)
		w, e := z.CreateHeader(h)
		if e != nil {
			return result, e
		}
		if _, e = w.Write(b); e != nil {
			return result, e
		}
	}
	if e = z.Close(); e != nil {
		return result, e
	}
	info, e := out.Stat()
	if e != nil {
		return result, e
	}
	result.Bytes = info.Size()
	// 客户端也限制整个发布包为512MB，不能产生无法安装的READY版本。
	if result.Bytes > MaxExpanded {
		return result, fmt.Errorf("规范资源包超过512MB")
	}
	result.SHA256 = hex.EncodeToString(digest.Sum(nil))
	success = true
	return result, nil
}
