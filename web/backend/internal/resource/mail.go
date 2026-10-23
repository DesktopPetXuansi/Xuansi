package resource

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"net/textproto"
	"strings"
	"time"

	"github.com/google/uuid"
)

// SMTP连接带截止时间；正文不写入日志，避免验证与重置链接泄漏。
func (w *Worker) sendMail(ctx context.Context, payload json.RawMessage) (result error) {
	// 领取任务之外保留最终保护，暂停时不解析邮件、不连接 SMTP；调用方记录固定错误。
	if w.Config.MailDeliveryDisabled {
		return errors.New("邮件发送已暂停")
	}
	stage := "读取任务"
	// 阶段仅由本函数的固定文案赋值；保留排障类别，不向日志传递上游原文或包装错误。
	defer func() {
		if result == nil {
			return
		}
		var response *textproto.Error
		var network net.Error
		if errors.As(result, &response) {
			result = fmt.Errorf("邮件服务返回错误（%s），SMTP 状态码 %d", stage, response.Code)
			return
		}
		switch {
		case errors.Is(result, context.Canceled):
			result = fmt.Errorf("邮件处理已取消（%s）", stage)
		case errors.Is(result, context.DeadlineExceeded):
			result = fmt.Errorf("邮件处理超时（%s）", stage)
		case errors.As(result, &network):
			if network.Timeout() {
				result = fmt.Errorf("邮件处理超时（%s）", stage)
			} else {
				result = fmt.Errorf("邮件网络请求失败（%s）", stage)
			}
		default:
			result = fmt.Errorf("邮件处理失败（%s），请检查发信服务配置及队列状态", stage)
		}
	}()
	var in struct {
		To, Subject, Body string
		RegistrationID    string `json:"registrationId"`
	}
	if e := json.Unmarshal(payload, &in); e != nil {
		return e
	}
	if in.RegistrationID != "" {
		stage = "检查注册状态"
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
	stage = "校验邮件头"
	if _, e := mail.ParseAddress(in.To); e != nil {
		return e
	}
	if strings.ContainsAny(in.Subject, "\r\n") || strings.ContainsAny(w.Config.SMTPFrom, "\r\n") {
		return fmt.Errorf("邮件头无效")
	}
	address := net.JoinHostPort(w.Config.SMTPHost, w.Config.SMTPPort)
	stage = "SMTP 连接"
	conn, e := (&net.Dialer{Timeout: 10 * time.Second}).DialContext(ctx, "tcp", address)
	if e != nil {
		return e
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(20 * time.Second))
	stage = "SMTP 握手"
	client, e := smtp.NewClient(conn, w.Config.SMTPHost)
	if e != nil {
		return e
	}
	defer client.Close()
	stage = "SMTP TLS"
	hasTLS, _ := client.Extension("STARTTLS")
	if hasTLS {
		if e = client.StartTLS(&tls.Config{ServerName: w.Config.SMTPHost, MinVersion: tls.VersionTLS12}); e != nil {
			return e
		}
	} else if w.Config.Environment == "production" {
		return fmt.Errorf("生产SMTP必须支持TLS")
	}
	if w.Config.SMTPUser != "" {
		stage = "SMTP 认证"
		if e = client.Auth(smtp.PlainAuth("", w.Config.SMTPUser, w.Config.SMTPPassword, w.Config.SMTPHost)); e != nil {
			return e
		}
	}
	stage = "SMTP 发件"
	if e = client.Mail(w.Config.SMTPFrom); e != nil {
		return e
	}
	stage = "SMTP 收件"
	if e = client.Rcpt(in.To); e != nil {
		return e
	}
	stage = "SMTP 正文"
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
	stage = "SMTP 结束"
	return client.Quit()
}
