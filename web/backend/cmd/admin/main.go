package main

import (
	"context"
	"flag"
	"github.com/google/uuid"
	"gorm.io/gorm"
	"log/slog"
	"os"
	"time"
	"xuansi/web/backend/internal/platform"
)

// 本机运维命令只提升已验证用户，不创建默认账号或密码。
func main() {
	email := flag.String("email", "", "已验证账号邮箱")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if *email == "" {
		log.Error("需要 -email")
		os.Exit(1)
	}
	c, e := platform.LoadConfig()
	if e != nil {
		log.Error("配置无效", "error", e)
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	db, e := platform.OpenDatabase(ctx, c.DatabaseURL)
	if e != nil {
		log.Error("数据库不可用", "error", e)
		os.Exit(1)
	}
	e = db.Transaction(func(tx *gorm.DB) error {
		u, e := gorm.G[platform.User](tx).Where("lower(email)=lower(?) AND email_verified AND status='ACTIVE'", *email).First(ctx)
		if e != nil {
			return e
		}
		if _, e = gorm.G[platform.User](tx).Where("id=?", u.ID).Update(ctx, "role", "ADMIN"); e != nil {
			return e
		}
		return gorm.G[platform.AuditLog](tx).Create(ctx, &platform.AuditLog{ID: uuid.NewString(), ActorID: &u.ID, Action: "ADMIN_PROMOTE_LOCAL", TargetID: u.ID, Details: []byte(`{}`), CreatedAt: time.Now()})
	})
	if e != nil {
		log.Error("提升管理员失败", "error", e)
		os.Exit(1)
	}
	log.Info("已提升经过验证的账号为管理员")
}
