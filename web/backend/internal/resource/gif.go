package resource

import (
	"encoding/binary"
	"fmt"
)

// 解码前遍历GIF块，限制帧数与累计像素，避免DecodeAll先分配巨量帧。
func validateGIF(b []byte) error {
	if len(b) < 13 || string(b[:6]) != "GIF89a" && string(b[:6]) != "GIF87a" {
		return fmt.Errorf("GIF头部无效")
	}
	pos := 13
	if b[10]&0x80 != 0 {
		pos += 3 * (1 << ((b[10] & 7) + 1))
	}
	frames := 0
	var pixels int64
	blocks := func() bool {
		for pos < len(b) {
			size := int(b[pos])
			pos++
			if size == 0 {
				return true
			}
			if pos+size > len(b) {
				return false
			}
			pos += size
		}
		return false
	}
	for pos < len(b) {
		marker := b[pos]
		pos++
		switch marker {
		case 0x21:
			if pos >= len(b) {
				return fmt.Errorf("GIF扩展截断")
			}
			pos++
			if !blocks() {
				return fmt.Errorf("GIF扩展无效")
			}
		case 0x2c:
			if pos+9 > len(b) {
				return fmt.Errorf("GIF帧截断")
			}
			width := int64(binary.LittleEndian.Uint16(b[pos+4:]))
			height := int64(binary.LittleEndian.Uint16(b[pos+6:]))
			pixels += width * height
			frames++
			if width <= 0 || height <= 0 || pixels > 64_000_000 || frames > 1000 {
				return fmt.Errorf("GIF帧数或累计像素超限")
			}
			packed := b[pos+8]
			pos += 9
			if packed&0x80 != 0 {
				pos += 3 * (1 << ((packed & 7) + 1))
			}
			if pos >= len(b) {
				return fmt.Errorf("GIF数据截断")
			}
			pos++
			if !blocks() {
				return fmt.Errorf("GIF压缩块无效")
			}
		case 0x3b:
			if frames == 0 {
				return fmt.Errorf("GIF无帧")
			}
			return nil
		default:
			return fmt.Errorf("GIF块标记无效")
		}
	}
	return fmt.Errorf("GIF缺少结束标记")
}
