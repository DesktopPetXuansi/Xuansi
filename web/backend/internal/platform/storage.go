package platform

import (
	"context"
	"fmt"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// ObjectStorage 仅暴露业务需要的对象操作；发布对象的随机键与上传键分离。
type ObjectStorage interface {
	Put(context.Context, string, io.Reader, int64, string) error
	Open(context.Context, string) (io.ReadCloser, error)
	Delete(context.Context, string) error
	PresignPut(context.Context, string, int64) (string, error)
}
type LocalStorage struct{ Root string }

func (s LocalStorage) resolve(key string) (string, error) {
	if key == "" || strings.ContainsAny(key, "\\:\x00") || strings.HasPrefix(key, "/") || strings.Contains(key, "..") {
		return "", fmt.Errorf("无效存储键")
	}
	return filepath.Join(s.Root, filepath.FromSlash(key)), nil
}
func (s LocalStorage) Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error {
	p, e := s.resolve(key)
	if e != nil {
		return e
	}
	if e = os.MkdirAll(filepath.Dir(p), 0700); e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(p), ".upload-*")
	if e != nil {
		return e
	}
	name := f.Name()
	defer os.Remove(name)
	n, e := io.Copy(f, io.LimitReader(&contextReader{ctx, r}, size+1))
	closeErr := f.Close()
	if e != nil {
		return e
	}
	if closeErr != nil {
		return closeErr
	}
	if n != size {
		return fmt.Errorf("实际大小与预期不符")
	}
	return os.Rename(name, p)
}
func (s LocalStorage) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	p, e := s.resolve(key)
	if e != nil {
		return nil, e
	}
	return os.Open(p)
}
func (s LocalStorage) Delete(ctx context.Context, key string) error {
	p, e := s.resolve(key)
	if e != nil {
		return e
	}
	e = os.Remove(p)
	if os.IsNotExist(e) {
		return nil
	}
	return e
}
func (s LocalStorage) PresignPut(context.Context, string, int64) (string, error) { return "", nil }

type contextReader struct {
	ctx context.Context
	r   io.Reader
}

func (r *contextReader) Read(b []byte) (int, error) {
	if e := r.ctx.Err(); e != nil {
		return 0, e
	}
	return r.r.Read(b)
}

type S3Storage struct {
	Client    *s3.Client
	Bucket    string
	Presigner *s3.PresignClient
}

func NewStorage(ctx context.Context, c Config) (ObjectStorage, error) {
	if c.StorageDriver == "local" {
		return LocalStorage{c.StoragePath}, nil
	}
	cfg, e := config.LoadDefaultConfig(ctx, config.WithRegion(c.S3Region), config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider(c.S3AccessKey, c.S3SecretKey, "")))
	if e != nil {
		return nil, e
	}
	client := s3.NewFromConfig(cfg, func(o *s3.Options) { o.BaseEndpoint = aws.String(c.S3Endpoint); o.UsePathStyle = true })
	// 由 SDK 在签名前选择公网端点；不能签名后替换 URL 的 Host 或路径。
	presigner := s3.NewPresignClient(client, s3.WithPresignClientFromClientOptions(func(o *s3.Options) {
		if c.S3PublicEndpoint != "" {
			o.BaseEndpoint = aws.String(c.S3PublicEndpoint)
		}
	}))
	return S3Storage{Client: client, Bucket: c.S3Bucket, Presigner: presigner}, nil
}
func (s S3Storage) Put(ctx context.Context, key string, r io.Reader, size int64, contentType string) error {
	_, e := s.Client.PutObject(ctx, &s3.PutObjectInput{Bucket: aws.String(s.Bucket), Key: aws.String(key), Body: r, ContentLength: aws.Int64(size), ContentType: aws.String(contentType)})
	return e
}
func (s S3Storage) Open(ctx context.Context, key string) (io.ReadCloser, error) {
	o, e := s.Client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(s.Bucket), Key: aws.String(key)})
	if e != nil {
		return nil, e
	}
	return o.Body, nil
}
func (s S3Storage) Delete(ctx context.Context, key string) error {
	_, e := s.Client.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: aws.String(s.Bucket), Key: aws.String(key)})
	return e
}
func (s S3Storage) PresignPut(ctx context.Context, key string, size int64) (string, error) {
	p, e := s.Presigner.PresignPutObject(ctx, &s3.PutObjectInput{Bucket: aws.String(s.Bucket), Key: aws.String(key), ContentLength: aws.Int64(size), ContentType: aws.String("application/octet-stream")}, s3.WithPresignExpires(15*time.Minute))
	if e != nil {
		return "", e
	}
	return p.URL, nil
}
