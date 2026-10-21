package resource

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"

	"github.com/google/uuid"
)

// SMTP连接带截止时间；正文不写入日志，避免验证与重置链接泄漏。
func (w *Worker) sendMail(ctx context.Context, payload json.RawMessage) error {
	var in struct {
		To, Subject, Body string
		RegistrationID    string `json:"registrationId"`
	}
	if e := json.Unmarshal(payload, &in); e != nil {
		return e
	}
	if in.RegistrationID != "" {
		if uuid.Validate(in.RegistrationID) != nil {
			return fmt.Errorf("注册邮件任务无效")
		}
		var active int64
		if err := w.DB.WithContext(ctx).Table("registration_challenges").Where("id=? AND consumed_at IS NULL AND expires_at>now() AND attempts<5", in.RegistrationID).Count(&active).Error; err != nil {
			return fmt.Errorf("注册邮件状态暂时无法读取")
		}
		if active == 0 {
			// 重发、已消费和已过期邮件正常结束，任务终态沿用既有正文清理。
			w.Log.Info("失效注册邮件已跳过", "challengeId", in.RegistrationID)
			return nil
		}
	}
	if _, e := mail.ParseAddress(in.To); e != nil {
		return e
	}
	if strings.ContainsAny(in.Subject, "\r\n") || strings.ContainsAny(w.Config.SMTPFrom, "\r\n") {
		return fmt.Errorf("邮件头无效")
	}
	address := net.JoinHostPort(w.Config.SMTPHost, w.Config.SMTPPort)
	conn, e := (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, "tcp", address)
	if e != nil {
		return e
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(20 * time.Second))
	client, e := smtp.NewClient(conn, w.Config.SMTPHost)
	if e != nil {
		return e
	}
	defer client.Close()
	hasTLS, _ := client.Extension("STARTTLS")
	if hasTLS {
		if e = client.StartTLS(&tls.Config{ServerName: w.Config.SMTPHost, MinVersion: tls.VersionTLS12}); e != nil {
			return e
		}
	} else if w.Config.Environment == "production" {
		return fmt.Errorf("生产SMTP必须支持TLS")
	}
	if w.Config.SMTPUser != "" {
		if e = client.Auth(smtp.PlainAuth("", w.Config.SMTPUser, w.Config.SMTPPassword, w.Config.SMTPHost)); e != nil {
			return e
		}
	}
	if e = client.Mail(w.Config.SMTPFrom); e != nil {
		return e
	}
	if e = client.Rcpt(in.To); e != nil {
		return e
	}
	body, e := client.Data()
	if e != nil {
		return e
	}
	_, e = fmt.Fprintf(body, "From: %s\r\nTo: %s\r\nSubject: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n", w.Config.SMTPFrom, in.To, in.Subject, in.Body)
	if e != nil {
		return e
	}
	if e = body.Close(); e != nil {
		return e
	}
	return client.Quit()
}
