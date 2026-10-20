// feedback 为内存受限主机提供独立收件进程，复用平台校验、事务和可靠投递。
package main

import (
	"context"
	"errors"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	backend "xuansi/web/backend"
	"xuansi/web/backend/internal/api"
	"xuansi/web/backend/internal/platform"
	"xuansi/web/backend/internal/resource"
)

func main() {
	migrate := flag.Bool("migrate", false, "启动前执行SQL迁移")
	only := flag.Bool("migrate-only", false, "执行迁移后退出")
	flag.Parse()
	log := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, log, *migrate, *only); err != nil {
		log.Error("反馈服务停止", "error", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, log *slog.Logger, migrate, only bool) error {
	c, err := platform.LoadFeedbackConfig()
	if err != nil {
		return err
	}
	db, err := platform.OpenDatabase(ctx, c.DatabaseURL)
	if err != nil {
		return errors.New("反馈数据库连接失败，请检查服务器配置")
	}
	sql, err := db.DB()
	if err != nil {
		return errors.New("无法获取反馈数据库连接池")
	}
	defer sql.Close()
	// API 与顺序 worker 共用小连接池，不挤占同机其他项目的数据库容量。
	sql.SetMaxIdleConns(2)
	sql.SetMaxOpenConns(4)
	if migrate || only {
		if err := platform.Migrate(ctx, db, backend.Migrations); err != nil {
			return errors.New("反馈数据库迁移失败")
		}
		log.Info("反馈数据库迁移完成")
	}
	if only {
		return nil
	}
	workCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	worker := &resource.Worker{DB: db, Config: c, Log: log}
	workerDone := make(chan error, 1)
	go func() { workerDone <- worker.Run(workCtx) }()
	s := &api.Server{DB: db, Config: c, Log: log}
	server := &http.Server{
		Addr: c.Address, Handler: s.FeedbackRouter(), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 << 10,
	}
	serveDone := make(chan error, 1)
	go func() { serveDone <- server.ListenAndServe() }()
	log.Info("反馈服务已启动", "address", c.Address, "githubEnabled", c.FeedbackGitHubRepository != "")
	var serveErr error
	select {
	case <-ctx.Done():
	case err := <-serveDone:
		if !errors.Is(err, http.ErrServerClosed) {
			serveErr = errors.New("反馈HTTP监听失败")
		}
	}
	cancel()
	// 先停止新请求并等待在途事务、投递退出，再关闭数据库。
	shutdown, stop := context.WithTimeout(context.Background(), 10*time.Second)
	defer stop()
	if err := server.Shutdown(shutdown); err != nil {
		_ = server.Close()
		return errors.New("反馈HTTP停止超时")
	}
	select {
	case <-workerDone:
	case <-shutdown.Done():
		return errors.New("反馈后台任务停止超时")
	}
	log.Info("反馈服务已停止")
	return serveErr
}
