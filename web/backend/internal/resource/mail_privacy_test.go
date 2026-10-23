package resource

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net"
	"strings"
	"testing"
	"time"

	"xuansi/web/backend/internal/platform"
)

// 取消请求不触发外部连接，诊断保留固定阶段而不保留目标主机或邮箱。
func TestCanceledMailKeepsSafeDiagnosticStage(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	worker := Worker{Config: platform.Config{SMTPHost: "smtp-private.example.invalid", SMTPPort: "587"}}
	err := worker.sendMail(ctx, json.RawMessage(`{"to":"recipient-private@example.invalid","subject":"隔离测试"}`))
	if err == nil || !strings.Contains(err.Error(), "已取消（SMTP 连接）") || strings.Contains(err.Error(), "private") {
		t.Fatal("取消诊断应保留固定阶段和类别，并移除目标身份")
	}
}

// 即便未来有新调用绕过队列领取，暂停开关仍应在解析正文和连接 SMTP 前生效。
func TestPausedMailDoesNotConnectToSMTP(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal("无法启动隔离 SMTP 探针")
	}
	t.Cleanup(func() { _ = listener.Close() })
	connected := make(chan struct{}, 1)
	go func() {
		connection, err := listener.Accept()
		if err == nil {
			connected <- struct{}{}
			_ = connection.Close()
		}
	}()
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	worker := Worker{Config: platform.Config{MailDeliveryDisabled: true, SMTPHost: host, SMTPPort: port}}
	err = worker.sendMail(context.Background(), json.RawMessage(`{"to":"recipient@example.invalid","subject":"隔离测试","body":"不应发送"}`))
	if err == nil || err.Error() != "邮件发送已暂停" {
		t.Fatal("暂停发送时应返回固定错误，不继续处理邮件")
	}
	select {
	case <-connected:
		t.Fatal("暂停状态连接了 SMTP")
	case <-time.After(100 * time.Millisecond):
	}
	// 非法任务也必须先由暂停开关拒绝，不能暴露正文解析错误。
	err = worker.sendMail(context.Background(), json.RawMessage(`{`))
	if err == nil || err.Error() != "邮件发送已暂停" {
		t.Fatal("暂停开关未先于任务解析生效")
	}
}

// 模拟 SMTP 拒信回显地址，验证上游错误不会被 Worker 写入日志或任务诊断。
func TestMailFailureDoesNotExposeSMTPIdentity(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal("无法启动隔离 SMTP 服务")
	}
	t.Cleanup(func() { _ = listener.Close() })
	done := make(chan struct{})
	go func() {
		defer close(done)
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		defer connection.Close()
		_ = connection.SetDeadline(time.Now().Add(5 * time.Second))
		_, _ = io.WriteString(connection, "220 mail.example.invalid ESMTP\r\n")
		reader := bufio.NewReader(connection)
		for {
			line, err := reader.ReadString('\n')
			if err != nil {
				return
			}
			if strings.HasPrefix(line, "RCPT TO:") {
				_, _ = io.WriteString(connection, "550 private-sender@example.invalid private-recipient@example.invalid smtp-private-marker\r\n")
				return
			}
			_, _ = io.WriteString(connection, "250 OK\r\n")
		}
	}()
	host, port, _ := net.SplitHostPort(listener.Addr().String())
	worker := Worker{Config: platform.Config{SMTPHost: host, SMTPPort: port, SMTPFrom: "private-sender@example.invalid", Environment: "development"}}
	payload, _ := json.Marshal(map[string]string{"to": "private-recipient@example.invalid", "subject": "测试验证码", "body": "仅在隔离测试中运行"})
	err = worker.sendMail(context.Background(), payload)
	if err == nil {
		t.Fatal("SMTP 拒信未被报告")
	}
	for _, value := range []string{"private-sender", "private-recipient", "smtp-private-marker"} {
		if strings.Contains(err.Error(), value) {
			t.Fatal("SMTP 错误暴露发信身份或上游原始诊断")
		}
	}
	if !strings.Contains(err.Error(), "550") {
		t.Fatal("缺少不含个人信息的 SMTP 状态码")
	}
	if !strings.Contains(err.Error(), "SMTP 收件") {
		t.Fatal("脱敏后仍应保留固定的失败阶段")
	}
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("隔离 SMTP 服务未退出")
	}
}
