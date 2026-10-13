package resource

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image"
	"path"
	"sort"
	"strings"
)

// 原始Cubism文档校验与ZIP构建分开；运行兼容性由原生客户端实际试载。
func validateSingle(kind, name string, b []byte) error {
	if kind == "IMAGE" || kind == "ANIMATION" {
		if kind == "ANIMATION" && !strings.HasSuffix(strings.ToLower(name), ".gif") {
			return fmt.Errorf("透明动图首期使用GIF格式")
		}
		_, _, e := image.DecodeConfig(bytes.NewReader(b))
		return e
	}
	if len(b) > 8<<20 {
		return fmt.Errorf("JSON 超过8MB")
	}
	var doc struct {
		Version int               `json:"Version"`
		Type    string            `json:"Type"`
		Curves  []json.RawMessage `json:"Curves"`
		Meta    *struct {
			Duration *float64 `json:"Duration"`
		} `json:"Meta"`
		Parameters []struct {
			ID    string   `json:"Id"`
			Value *float64 `json:"Value"`
			Blend string   `json:"Blend"`
		} `json:"Parameters"`
	}
	if e := json.Unmarshal(b, &doc); e != nil {
		return e
	}
	if kind == "MOTION" {
		if !strings.HasSuffix(name, ".motion3.json") || doc.Version != 3 || len(doc.Curves) == 0 || doc.Meta == nil || doc.Meta.Duration == nil || *doc.Meta.Duration <= 0 || *doc.Meta.Duration > 3600 {
			return fmt.Errorf("动作格式无效")
		}
	} else if kind == "EXPRESSION" {
		if !strings.HasSuffix(name, ".exp3.json") || doc.Type != "Live2D Expression" || len(doc.Parameters) == 0 {
			return fmt.Errorf("表情格式无效")
		}
		for _, p := range doc.Parameters {
			if p.ID == "" || p.Value == nil || p.Blend != "" && p.Blend != "Add" && p.Blend != "Multiply" && p.Blend != "Overwrite" {
				return fmt.Errorf("表情参数无效")
			}
		}
	}
	return nil
}
func validateModel(files map[string][]byte, entry string, m *Manifest) error {
	if len(files[entry]) > 8<<20 {
		return fmt.Errorf("模型入口JSON超过8MB")
	}
	var doc struct {
		Version    int `json:"Version"`
		References struct {
			Moc         string   `json:"Moc"`
			Textures    []string `json:"Textures"`
			Physics     string   `json:"Physics"`
			Pose        string   `json:"Pose"`
			DisplayInfo string   `json:"DisplayInfo"`
			UserData    string   `json:"UserData"`
			Expressions []struct {
				Name string `json:"Name"`
				File string `json:"File"`
			} `json:"Expressions"`
			Motions map[string][]struct {
				File  string `json:"File"`
				Sound string `json:"Sound"`
			} `json:"Motions"`
		} `json:"FileReferences"`
		Groups []struct {
			Target string   `json:"Target"`
			Name   string   `json:"Name"`
			IDs    []string `json:"Ids"`
		} `json:"Groups"`
	}
	if e := json.Unmarshal(files[entry], &doc); e != nil {
		return e
	}
	if doc.Version != 3 || doc.References.Moc == "" || len(doc.References.Textures) == 0 {
		return fmt.Errorf("模型必须包含MOC和纹理")
	}
	require := func(ref string) error {
		if ref == "" {
			return nil
		}
		if !SafePath(ref) {
			return fmt.Errorf("模型引用路径非法")
		}
		resolved := path.Join(path.Dir(entry), ref)
		if _, ok := files[resolved]; !ok {
			return fmt.Errorf("缺失引用：%s", ref)
		}
		return nil
	}
	refs := append([]string{doc.References.Moc, doc.References.Physics, doc.References.Pose, doc.References.DisplayInfo, doc.References.UserData}, doc.References.Textures...)
	caps := &Capabilities{Parameters: map[string]string{}, Motions: []string{}, Expressions: []string{}}
	for _, exp := range doc.References.Expressions {
		if exp.File == "" {
			return fmt.Errorf("表情文件引用不能为空")
		}
		refs = append(refs, exp.File)
		caps.Expressions = append(caps.Expressions, exp.Name)
	}
	for group, motions := range doc.References.Motions {
		for _, motion := range motions {
			if motion.File == "" {
				return fmt.Errorf("动作文件引用不能为空")
			}
			refs = append(refs, motion.File, motion.Sound)
		}
		caps.Motions = append(caps.Motions, group)
	}
	for _, texture := range doc.References.Textures {
		if texture == "" {
			return fmt.Errorf("纹理引用不能为空")
		}
	}
	for _, ref := range refs {
		if e := require(ref); e != nil {
			return e
		}
	}
	moc := files[path.Join(path.Dir(entry), doc.References.Moc)]
	if len(moc) < 8 || string(moc[:4]) != "MOC3" {
		return fmt.Errorf("MOC3 头部无效")
	}
	for _, group := range doc.Groups {
		if group.Target == "Parameter" && len(group.IDs) > 0 && (group.Name == "EyeBlink" || group.Name == "LipSync") {
			caps.Parameters[group.Name] = group.IDs[0]
		}
	}
	sort.Strings(caps.Motions)
	m.Capabilities = caps
	return nil
}
