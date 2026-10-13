package platform

import (
	"strings"
	"testing"
)

// 密码和凭据回归覆盖错误密码、独立盐与固定长度摘要。
func TestPassword(t *testing.T) {
	hash, err := HashPassword("a-strong-password-123")
	if err != nil {
		t.Fatal(err)
	}
	if !CheckPassword(hash, "a-strong-password-123") || CheckPassword(hash, "wrong") {
		t.Fatal("密码校验失败")
	}
	other, _ := HashPassword("a-strong-password-123")
	if hash == other {
		t.Fatal("未使用独立盐")
	}
	if len(Digest("token")) != 64 {
		t.Fatal("摘要长度不正确")
	}
}

// 密码提示说的是字符，中文和 Emoji 不应被 UTF-8 字节或 UTF-16 长度误判。
func TestPasswordCharacterBoundaries(t *testing.T) {
	for _, test := range []struct {
		name, password string
		accepted       bool
	}{
		{"11个ASCII", strings.Repeat("a", 11), false},
		{"11个中文", strings.Repeat("字", 11), false},
		{"12个ASCII", strings.Repeat("a", 12), true},
		{"12个中文", strings.Repeat("字", 12), true},
		{"128个Emoji", strings.Repeat("🐱", 128), true},
		{"129个ASCII", strings.Repeat("a", 129), false},
	} {
		t.Run(test.name, func(t *testing.T) {
			hash, err := HashPassword(test.password)
			if (err == nil) != test.accepted {
				t.Fatalf("字符边界未按12至128个字符校验，接受=%t", err == nil)
			}
			if test.accepted && !CheckPassword(hash, test.password) {
				t.Fatal("符合字符规则的密码无法登录")
			}
		})
	}
}
