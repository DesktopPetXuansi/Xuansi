package platform

import "time"

// 私有消息永不嵌入 FeedbackEntry，避免管理员列表或 GitHub 任务意外带出正文。
type FeedbackMessage struct {
	ID             string    `json:"id"`
	FeedbackID     string    `json:"-"`
	AuthorRole     string    `json:"authorRole"`
	AuthorName     string    `json:"authorName,omitempty"`
	Body           string    `json:"body"`
	CreatedAt      time.Time `json:"createdAt"`
	IdempotencyKey string    `json:"-"`
	RequestHash    string    `json:"-"`
}

func (FeedbackMessage) TableName() string { return "feedback_messages" }
