package resource

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// 校验器不能把路径越界和脚本当作普通资源。
func TestUnsafePackage(t *testing.T) {
	for _, name := range []string{"../evil.json", "C:/evil.json", "folder/run.js", "CON.json", "folder/a:stream.json"} {
		var b bytes.Buffer
		z := zip.NewWriter(&b)
		w, _ := z.Create(name)
		_, _ = w.Write([]byte("{}"))
		_ = z.Close()
		p := filepath.Join(t.TempDir(), "input.zip")
		_ = os.WriteFile(p, b.Bytes(), 0600)
		_, err := BuildPackage(p, "MODEL", "", "r", "v", "1.0.0", "")
		if err == nil {
			t.Errorf("危险文件被接受：%s", name)
		}
	}
}

func TestSafeUploadFilename(t *testing.T) {
	for _, name := range []string{"a:b.zip", "..\\evil.zip", "CON.zip", "folder/file.zip", "/evil.zip", "a\x00.zip", "thing.zip "} {
		if SafeUploadFilename(name) {
			t.Errorf("危险上传名被接受：%q", name)
		}
	}
	for _, name := range []string{"model.zip", "smile.exp3.json", "pet.png"} {
		if !SafeUploadFilename(name) {
			t.Errorf("正常上传名被拒绝：%s", name)
		}
	}
}

func TestWindowsForbiddenCharacters(t *testing.T) {
	for _, name := range []string{"foo?.txt", "foo*.png", "a|b.json", "a<b.txt", "a>b.txt", "a\"b.txt", "installed-manifest.json"} {
		if SafePath(name) || SafeUploadFilename(name) {
			t.Errorf("Windows危险名被接受：%q", name)
		}
	}
}
func TestExpressionPackage(t *testing.T) {
	p := filepath.Join(t.TempDir(), "smile.exp3.json")
	_ = os.WriteFile(p, []byte(`{"Type":"Live2D Expression","Parameters":[{"Id":"ParamSmile","Value":1,"Blend":"Add"}]}`), 0600)
	pkg, err := BuildPackage(p, "EXPRESSION", "smile.exp3.json", "r", "v", "1.0.0", "")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(pkg.Path)
	if pkg.Manifest.Entrypoint != "smile.exp3.json" || len(pkg.Manifest.Files) != 1 {
		t.Fatal("清单不正确")
	}
}
