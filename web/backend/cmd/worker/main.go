package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

// worker 只记录任务ID与结果，邮件正文和下载凭据不进日志。
func main() {
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	c, e := platform.LoadConfig()
	if e != nil {
		log.Error("配置错误", "error", e)
		os.Exit(1)
	}
	db, e := platform.OpenDatabase(ctx, c.DatabaseURL)
	if e != nil {
		log.Error("数据库连接失败", "error", e)
		os.Exit(1)
	}
	storage, e := platform.NewStorage(ctx, c)
	if e != nil {
		log.Error("存储初始化失败", "error", e)
		os.Exit(1)
	}
	w := resource.Worker{DB: db, Storage: storage, Config: c, Log: log}
	log.Info("worker已启动")
	if e = w.Run(ctx); e != nil {
		log.Error("worker停止", "error", e)
		os.Exit(1)
	}
}
