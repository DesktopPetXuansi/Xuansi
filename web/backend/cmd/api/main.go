package main

import (
	"context"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
	backend "xuansi/web/backend"
	"xuansi/web/backend/internal/api"
	"xuansi/web/backend/internal/oauth"
	"xuansi/web/backend/internal/platform"
)

// API 与 worker 分离，迁移必须显式启用。
func main() {
	migrate := flag.Bool("migrate", false, "启动前执行SQL迁移")
	only := flag.Bool("migrate-only", false, "执行迁移后退出")
	flag.Parse()
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
	if *migrate || *only {
		if e = platform.Migrate(ctx, db, backend.Migrations); e != nil {
			log.Error("迁移失败", "error", e)
			os.Exit(1)
		}
	}
	if *only {
		return
	}
	storage, e := platform.NewStorage(ctx, c)
	if e != nil {
		log.Error("存储初始化失败", "error", e)
		os.Exit(1)
	}
	s := &api.Server{DB: db, Config: c, Storage: storage, Log: log}
	s.OAuth = oauth.New(db, c, api.CurrentUser)
	server := &http.Server{Addr: c.Address, Handler: s.Router(), ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 5 * time.Minute, WriteTimeout: 5 * time.Minute, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	log.Info("API已启动", "address", c.Address, "storage", c.StorageDriver)
	if e = server.ListenAndServe(); e != nil && e != http.ErrServerClosed {
		log.Error("API停止", "error", e)
		os.Exit(1)
	}
}
