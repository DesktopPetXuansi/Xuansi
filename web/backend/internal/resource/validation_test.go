package resource

import (
	"archive/zip"
	"bytes"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"testing"
)

// 两端消费同一model3引用样例，确保可选空值不会只在其中一端失败。
func TestSharedOptionalModelReferences(t *testing.T) {
	document, e := os.ReadFile("../../../contracts/fixtures/model-references.json")
	if e != nil {
		t.Fatal(e)
	}
	var texture bytes.Buffer
	if e = png.Encode(&texture, image.NewRGBA(image.Rect(0, 0, 4, 4))); e != nil {
		t.Fatal(e)
	}
	files := map[string][]byte{"pet.model3.json": document, "pet.moc3": []byte("MOC3\x01\x00\x00\x00test"), "texture.png": texture.Bytes(), "idle.motion3.json": []byte(`{"Version":3,"Meta":{"Duration":1},"Curves":[]}`)}
	var content bytes.Buffer
	archive := zip.NewWriter(&content)
	for name, raw := range files {
		entry, e := archive.Create(name)
		if e != nil {
			t.Fatal(e)
		}
		if _, e = entry.Write(raw); e != nil {
			t.Fatal(e)
		}
	}
	if e = archive.Close(); e != nil {
		t.Fatal(e)
	}
	input := filepath.Join(t.TempDir(), "input.zip")
	if e = os.WriteFile(input, content.Bytes(), 0600); e != nil {
		t.Fatal(e)
	}
	pkg, e := BuildPackage(input, "MODEL", "pet.model3.json", "r", "v", "1.0.0", "")
	if e != nil {
		t.Fatal(e)
	}
	defer os.Remove(pkg.Path)
	if len(pkg.Manifest.Files) != 4 {
		t.Fatal("共享模型包缺少文件")
	}
	for _, invalid := range []string{`{"Version":3,"FileReferences":{"Moc":"pet.moc3","Textures":[""]}}`, `{"Version":3,"FileReferences":{"Moc":"","Textures":["texture.png"]}}`} {
		files["pet.model3.json"] = []byte(invalid)
		if e = validateModel(files, "pet.model3.json", &Manifest{}); e == nil {
			t.Fatal("必需模型引用允许留空")
		}
	}
}

func TestMotionRequiresClientCompatibleDuration(t *testing.T) {
	for _, doc := range []string{`{"Version":3,"Curves":[{}]}`, `{"Version":3,"Meta":{"Duration":0},"Curves":[{}]}`, `{"Version":3,"Meta":{"Duration":3601},"Curves":[{}]}`} {
		if e := validateSingle("MOTION", "idle.motion3.json", []byte(doc)); e == nil {
			t.Fatal("客户端必然拒绝的动作被接受")
		}
	}
	if e := validateSingle("EXPRESSION", "smile.exp3.json", []byte(`{"Type":"Live2D Expression","Parameters":[{"Id":"ParamSmile"}]}`)); e == nil {
		t.Fatal("缺少参数值的表情被接受")
	}
	if e := validateSingle("EXPRESSION", "smile.exp3.json", []byte(`{"Type":"Live2D Expression","Parameters":[{"Id":"ParamSmile","Value":1}]}`)); e != nil {
		t.Fatal("默认Add表情被拒绝", e)
	}
}

func TestStaticWebPPackage(t *testing.T) {
	pkg, e := BuildPackage("testdata/plain.webp", "IMAGE", "plain.webp", "r", "v", "1.0.0", "")
	if e != nil {
		t.Fatal(e)
	}
	defer os.Remove(pkg.Path)
	if len(pkg.Manifest.Files) != 1 || pkg.Manifest.Entrypoint != "plain.webp" {
		t.Fatal("静态WebP清单不正确")
	}
}
