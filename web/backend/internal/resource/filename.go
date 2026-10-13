package resource

import (
	"path"
	"strings"
)

// 上传可接受ZIP容器，但文件名本身必须满足客户端跨平台路径边界。
func SafeUploadFilename(name string) bool {
	if path.Base(name) != name || len(name) > 200 {
		return false
	}
	if strings.HasSuffix(name, ".zip") {
		return SafePath(strings.TrimSuffix(name, ".zip") + ".txt")
	}
	return SafePath(name)
}
