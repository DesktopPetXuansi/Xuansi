package api

import (
	"archive/zip"
	"bytes"
	"context"
	"gorm.io/gorm"
	"image"
	"image/png"
	"testing"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

type createdVersion struct {
	Version platform.ResourceVersion `json:"version"`
	Upload  platform.Upload          `json:"upload"`
}

func uploadReady(t *testing.T, c *testClient, w *resource.Worker, res platform.Resource, version, filename string, content []byte, target string) createdVersion {
	t.Helper()
	input := map[string]interface{}{"version": version, "filename": filename, "expectedBytes": len(content)}
	if target != "" {
		input["targetModelVersionId"] = target
	}
	row := data[createdVersion](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions", input, 201, ""))
	c.call("PUT", row.Upload.URL, content, 204, "")
	c.call("POST", "/api/v1/uploads/"+row.Upload.ID+"/completion", map[string]string{}, 202, "")
	for i := 0; i < 8; i++ {
		if e := w.Tick(context.Background()); e != nil {
			t.Fatal(e)
		}
	}
	row.Upload = data[platform.Upload](t, c.call("GET", "/api/v1/uploads/"+row.Upload.ID, nil, 200, ""))
	if row.Upload.Status != "READY" {
		t.Fatalf("版本校验未就绪：%+v", row.Upload)
	}
	return row
}
func modelFixture(t *testing.T) []byte {
	t.Helper()
	var imageBytes bytes.Buffer
	_ = png.Encode(&imageBytes, image.NewRGBA(image.Rect(0, 0, 4, 4)))
	files := map[string][]byte{"model.model3.json": []byte(`{"Version":3,"FileReferences":{"Moc":"model.moc3","Textures":["texture.png"]}}`), "model.moc3": []byte("MOC3\x01\x00\x00\x00test-structure-only"), "texture.png": imageBytes.Bytes()}
	var out bytes.Buffer
	z := zip.NewWriter(&out)
	for name, content := range files {
		f, e := z.Create(name)
		if e != nil {
			t.Fatal(e)
		}
		_, _ = f.Write(content)
	}
	_ = z.Close()
	return out.Bytes()
}

// 这里的MOC为结构测试夹具，不宣称真实Cubism渲染兼容。
func TestPostgresDependenciesIsolationAndDeletion(t *testing.T) {
	s, c, w := setup(t)
	owner := registered(t, s, c, "model-owner@example.com")
	model := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "MODEL", "name": "结构夹具模型"}, 201, ""))
	v := uploadReady(t, c, w, model, "1.0.0", "model.zip", modelFixture(t), "")
	other := &testClient{t: t, handler: c.handler}
	other.call("GET", "/api/v1/auth/csrf", nil, 200, "")
	registered(t, s, other, "other@example.com")
	other.call("GET", "/api/v1/resources/"+model.ID, nil, 404, "")
	other.call("PATCH", "/api/v1/resources/"+model.ID, map[string]string{"name": "越权修改"}, 404, "")
	expression := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "EXPRESSION", "name": "微笑"}, 201, ""))
	body := []byte(`{"Type":"Live2D Expression","Parameters":[{"Id":"ParamSmile","Value":1,"Blend":"Add"}]}`)
	c.call("POST", "/api/v1/resources/"+expression.ID+"/versions", map[string]interface{}{"version": "1.0.0", "filename": "smile.exp3.json", "expectedBytes": len(body)}, 400, "")
	otherExpr := data[platform.Resource](t, other.call("POST", "/api/v1/resources", map[string]string{"kind": "EXPRESSION", "name": "其他人表情"}, 201, ""))
	other.call("POST", "/api/v1/resources/"+otherExpr.ID+"/versions", map[string]interface{}{"version": "1.0.0", "filename": "smile.exp3.json", "expectedBytes": len(body), "targetModelVersionId": v.Version.ID}, 400, "")
	ev := uploadReady(t, c, w, expression, "1.0.0", "smile.exp3.json", body, v.Version.ID)
	manifest := data[resource.Manifest](t, c.call("GET", "/api/v1/resources/"+expression.ID+"/versions/"+ev.Version.ID+"/manifest", nil, 200, ""))
	if len(manifest.Dependencies) != 1 || manifest.Dependencies[0].VersionID != v.Version.ID || manifest.Dependencies[0].Relation != "TARGET_MODEL" {
		t.Fatal("模型版本依赖不精确")
	}
	versions := data[[]platform.ResourceVersion](t, c.call("GET", "/api/v1/resources/"+expression.ID+"/versions", nil, 200, ""))
	view := data[platform.ResourceVersion](t, c.call("GET", "/api/v1/resources/"+expression.ID+"/versions/"+ev.Version.ID, nil, 200, ""))
	if len(versions) != 1 || len(view.Dependencies) != 1 || view.Dependencies[0].VersionID != v.Version.ID || len(versions[0].Dependencies) != 1 {
		t.Fatal("版本列表与详情未返回精确依赖")
	}
	c.call("GET", "/api/v1/resources/"+model.ID+"/versions/"+ev.Version.ID, nil, 404, "")
	c.call("DELETE", "/api/v1/resources/"+model.ID, nil, 409, "")
	c.call("DELETE", "/api/v1/resources/"+expression.ID, nil, 204, "")
	c.call("DELETE", "/api/v1/resources/"+model.ID, nil, 204, "")
	c.call("GET", "/api/v1/resources/"+model.ID, nil, 404, "")
	var user platform.User
	if e := s.DB.Where("id=?", owner.ID).First(&user).Error; e != nil {
		t.Fatal(e)
	}
	if user.UsedBytes != 0 || user.ReservedBytes != 0 {
		t.Fatal("删除后未释放配额")
	}
}
func TestPostgresCancellationFailureAndCoverQuota(t *testing.T) {
	s, c, w := setup(t)
	owner := registered(t, s, c, "quota@example.com")
	res := data[platform.Resource](t, c.call("POST", "/api/v1/resources", map[string]string{"kind": "IMAGE", "name": "配额测试"}, 201, ""))
	for _, filename := range []string{"a:b.zip", "..\\evil.zip", "CON.zip"} {
		c.call("POST", "/api/v1/resources/"+res.ID+"/versions", map[string]interface{}{"version": "bad", "filename": filename, "expectedBytes": 100}, 400, "")
	}
	input := map[string]interface{}{"version": "cancel", "filename": "pet.png", "expectedBytes": 100}
	row := data[createdVersion](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions", input, 201, ""))
	c.call("DELETE", "/api/v1/uploads/"+row.Upload.ID, nil, 204, "")
	c.call("DELETE", "/api/v1/uploads/"+row.Upload.ID, nil, 204, "")
	input["version"] = "invalid"
	input["expectedBytes"] = 4
	bad := data[createdVersion](t, c.call("POST", "/api/v1/resources/"+res.ID+"/versions", input, 201, ""))
	c.call("PUT", bad.Upload.URL, []byte("oops"), 204, "")
	c.call("POST", "/api/v1/uploads/"+bad.Upload.ID+"/completion", map[string]string{}, 202, "")
	for i := 0; i < 8; i++ {
		if e := w.Tick(context.Background()); e != nil {
			t.Fatal(e)
		}
	}
	failed := data[platform.Upload](t, c.call("GET", "/api/v1/uploads/"+bad.Upload.ID, nil, 200, ""))
	if failed.Status != "FAILED" {
		t.Fatal("损坏图片未拒绝")
	}
	var pngBytes bytes.Buffer
	_ = png.Encode(&pngBytes, image.NewRGBA(image.Rect(0, 0, 4, 4)))
	var originalUsage int64
	for i := 0; i < 2; i++ {
		cover := data[platform.Upload](t, c.call("POST", "/api/v1/uploads", map[string]interface{}{"resourceId": res.ID, "purpose": "COVER", "filename": "cover.png", "expectedBytes": pngBytes.Len()}, 201, ""))
		c.call("PUT", cover.URL, pngBytes.Bytes(), 204, "")
		c.call("POST", "/api/v1/uploads/"+cover.ID+"/completion", map[string]string{}, 202, "")
		for j := 0; j < 4; j++ {
			if e := w.Tick(context.Background()); e != nil {
				t.Fatal(e)
			}
		}
		var user platform.User
		if e := s.DB.Where("id=?", owner.ID).First(&user).Error; e != nil {
			t.Fatal(e)
		}
		if user.ReservedBytes != 0 {
			t.Fatal("预留未释放")
		}
		if i == 0 {
			originalUsage = user.UsedBytes
		} else if user.UsedBytes != originalUsage {
			t.Fatal("相同封面替换重复扣容量")
		}
	}
	c.call("GET", "/api/v1/resources/"+res.ID+"/cover", nil, 200, "")
	c.call("DELETE", "/api/v1/resources/"+res.ID, nil, 204, "")
	var user platform.User
	if e := gorm.G[platform.User](s.DB).Where("id=?", owner.ID).Scan(context.Background(), &user); e != nil {
		t.Fatal(e)
	}
	if user.UsedBytes != 0 || user.ReservedBytes != 0 {
		t.Fatal("封面删除未释放容量")
	}
}
