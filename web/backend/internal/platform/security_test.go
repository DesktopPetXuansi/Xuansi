package platform

import "testing"

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
