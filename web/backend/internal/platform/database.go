package platform

import (
	"context"
	"embed"
	"github.com/pressly/goose/v3"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
	"time"
)

// SQL 迁移是唯一 schema 来源，禁止运行时 AutoMigrate。
func OpenDatabase(ctx context.Context, dsn string) (*gorm.DB, error) {
	db, e := gorm.Open(postgres.Open(dsn), &gorm.Config{TranslateError: true, Logger: logger.Default.LogMode(logger.Silent)})
	if e != nil {
		return nil, e
	}
	sql, e := db.DB()
	if e != nil {
		return nil, e
	}
	sql.SetMaxOpenConns(20)
	sql.SetMaxIdleConns(5)
	sql.SetConnMaxLifetime(30 * time.Minute)
	return db, sql.PingContext(ctx)
}
func Migrate(ctx context.Context, db *gorm.DB, files embed.FS) error {
	sql, e := db.DB()
	if e != nil {
		return e
	}
	goose.SetBaseFS(files)
	if e = goose.SetDialect("postgres"); e != nil {
		return e
	}
	return goose.UpContext(ctx, sql, "migrations")
}
