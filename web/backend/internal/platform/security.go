package platform

import (
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"golang.org/x/crypto/argon2"
	"strings"
	"unicode/utf8"
)

// 表单配置与服务端校验共用边界，字符长度按 Unicode 码点计数。
const PasswordMinLength = 12
const PasswordMaxLength = 128

func RandomToken() string {
	b := make([]byte, 32)
	if _, e := rand.Read(b); e != nil {
		panic(e)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}
func Digest(s string) string { v := sha256.Sum256([]byte(s)); return hex.EncodeToString(v[:]) }

// Argon2id 参数固定在服务端，解析数据库内容时也不接受任意成本。
func HashPassword(password string) (string, error) {
	length := utf8.RuneCountInString(password)
	if length < PasswordMinLength || length > PasswordMaxLength {
		return "", fmt.Errorf("密码须为%d至%d个字符", PasswordMinLength, PasswordMaxLength)
	}
	salt := make([]byte, 16)
	if _, e := rand.Read(salt); e != nil {
		return "", e
	}
	hash := argon2.IDKey([]byte(password), salt, 2, 64*1024, 2, 32)
	return "argon2id$" + base64.RawStdEncoding.EncodeToString(salt) + "$" + base64.RawStdEncoding.EncodeToString(hash), nil
}
func CheckPassword(encoded, password string) bool {
	parts := strings.Split(encoded, "$")
	// 登录保留已有密码的兼容性，只对新建/重设密码应用当前最小长度。
	if len(parts) != 3 || parts[0] != "argon2id" || utf8.RuneCountInString(password) > PasswordMaxLength {
		return false
	}
	salt, e := base64.RawStdEncoding.DecodeString(parts[1])
	if e != nil || len(salt) != 16 {
		return false
	}
	expected, e := base64.RawStdEncoding.DecodeString(parts[2])
	if e != nil || len(expected) != 32 {
		return false
	}
	actual := argon2.IDKey([]byte(password), salt, 2, 64*1024, 2, 32)
	return subtle.ConstantTimeCompare(actual, expected) == 1
}
