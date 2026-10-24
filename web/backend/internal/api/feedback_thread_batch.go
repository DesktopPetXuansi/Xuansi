package api

import "gorm.io/gorm"

// 可见列表每五秒刷新：批量读取昵称、末条消息和未读，避免逐会话N+1查询。
// 调用方已锁定所有反馈父行，三次批量读取与撤回/新消息保持同一快照边界。
func feedbackThreadBatch(tx *gorm.DB, rows []feedbackEntry, admin bool) ([]feedbackThread, error) {
	result := make([]feedbackThread, 0, len(rows))
	if len(rows) == 0 {
		return result, nil
	}
	ids, owners := make([]string, 0, len(rows)), make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.ID)
		if row.OwnerUserID != nil {
			owners = append(owners, *row.OwnerUserID)
		}
	}
	var people []struct{ ID, DisplayName string }
	if len(owners) > 0 {
		if err := tx.Table("users").Select("id,display_name").Where("id IN ?", owners).Find(&people).Error; err != nil {
			return nil, err
		}
	}
	names := make(map[string]string, len(people))
	for _, person := range people {
		names[person.ID] = person.DisplayName
	}
	var latest []feedbackMessage
	if err := tx.Select("DISTINCT ON (feedback_id) *").Where("feedback_id IN ?", ids).Order("feedback_id,created_at DESC,id DESC").Find(&latest).Error; err != nil {
		return nil, err
	}
	messages := make(map[string]feedbackMessage, len(latest))
	for _, message := range latest {
		messages[message.FeedbackID] = message
	}
	prefix, role := "owner", "ADMIN"
	if admin {
		prefix, role = "admin", "USER"
	}
	var counts []struct {
		FeedbackID string
		Unread     int64
	}
	boundary := "f." + prefix + "_read_at IS NULL OR f." + prefix + "_read_id IS NULL OR (m.created_at,m.id)>(f." + prefix + "_read_at,f." + prefix + "_read_id)"
	if err := tx.Table("feedback_messages AS m").Select("m.feedback_id,count(*) AS unread").Joins("JOIN feedback AS f ON f.id=m.feedback_id").Where("m.feedback_id IN ? AND m.author_role=?", ids, role).Where(boundary).Group("m.feedback_id").Find(&counts).Error; err != nil {
		return nil, err
	}
	unread := make(map[string]int64, len(counts))
	for _, count := range counts {
		unread[count.FeedbackID] = count.Unread
	}
	for _, row := range rows {
		out := feedbackThread{ID: row.ID, Title: row.Title, Status: row.Status, ModerationStatus: row.ModerationStatus, CreatedAt: row.CreatedAt, UpdatedAt: row.UpdatedAt, CanReply: canReplyFeedback(row), Participant: feedbackParticipant{"GUEST", "访客"}}
		if feedbackHidden(row) {
			out.Title = ""
			result = append(result, out)
			continue
		}
		if row.OwnerUserID != nil {
			out.Participant = feedbackParticipant{"ACCOUNT", names[*row.OwnerUserID]}
		}
		text := []rune(row.Description)
		if len(text) > 160 {
			text = text[:160]
		}
		out.Preview = string(text)
		out.UnreadCount = unread[row.ID]
		if admin && (row.AdminReadAt == nil || row.AdminReadID == nil || row.CreatedAt.After(*row.AdminReadAt) || row.CreatedAt.Equal(*row.AdminReadAt) && row.ID > *row.AdminReadID) {
			out.UnreadCount++
		}
		if message, exists := messages[row.ID]; exists {
			out.LastMessage = &message
		}
		result = append(result, out)
	}
	return result, nil
}
