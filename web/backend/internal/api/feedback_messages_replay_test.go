package api

import (
	"encoding/json"
	"github.com/google/uuid"
	"testing"
)

// 已接收消息保持同一编号与正文，附带状态反映父行当前进度，不能覆盖对方后续操作。
func TestPostgresMessagesReplayReturnsCurrentParentStatus(t *testing.T) {
	for _, firstAdmin := range []bool{true, false} {
		t.Run(map[bool]string{true: "管理员重试看见用户重开", false: "用户重试看见管理员解决"}[firstAdmin], func(t *testing.T) {
			s, c, id, token := conversationFixture(t)
			moderationAdmin(t, s, c)
			adminPath := "/api/v1/admin/feedback/" + id + "/messages"
			userPath := "/api/v1/feedback/" + id + "/messages"
			key := uuid.NewString()
			adminInput := map[string]interface{}{"body": "开发者确认解决", "resolve": true}
			userInput := map[string]string{"managementToken": token, "body": "用户补充后续问题"}
			firstPath, secondPath := userPath, adminPath
			var firstInput, secondInput interface{} = userInput, adminInput
			want := "RESOLVED"
			if firstAdmin {
				firstPath, secondPath = adminPath, userPath
				firstInput, secondInput = adminInput, userInput
				want = "NEW"
			}
			first := data[messageReceipt](t, messageCall(t, c, "POST", firstPath, key, firstInput, 201))
			messageCall(t, c, "POST", secondPath, uuid.NewString(), secondInput, 201)
			var beforeRow feedbackEntry
			if e := s.DB.Where("id=?", id).First(&beforeRow).Error; e != nil {
				t.Fatal(e)
			}
			var beforeMessages, beforeAudit, beforeQuota int64
			s.DB.Model(&feedbackMessage{}).Where("feedback_id=?", id).Count(&beforeMessages)
			s.DB.Table("audit_logs").Where("action LIKE 'feedback.message.%'").Count(&beforeAudit)
			s.DB.Table("feedback_submission_limits").Select("coalesce(sum(submissions),0)").Scan(&beforeQuota)
			retry := data[messageReceipt](t, messageCall(t, c, "POST", firstPath, key, firstInput, 200))
			oldMessage, _ := json.Marshal(first.Message)
			newMessage, _ := json.Marshal(retry.Message)
			if string(oldMessage) != string(newMessage) || retry.FeedbackStatus != want {
				t.Fatalf("重试未保留消息或返回过时状态: old=%s retry=%s status=%s want=%s", oldMessage, newMessage, retry.FeedbackStatus, want)
			}
			var afterRow feedbackEntry
			s.DB.Where("id=?", id).First(&afterRow)
			var afterMessages, afterAudit, afterQuota int64
			s.DB.Model(&feedbackMessage{}).Where("feedback_id=?", id).Count(&afterMessages)
			s.DB.Table("audit_logs").Where("action LIKE 'feedback.message.%'").Count(&afterAudit)
			s.DB.Table("feedback_submission_limits").Select("coalesce(sum(submissions),0)").Scan(&afterQuota)
			if afterRow.Status != want || !afterRow.UpdatedAt.Equal(beforeRow.UpdatedAt) || beforeMessages != afterMessages || beforeAudit != afterAudit || beforeQuota != afterQuota {
				t.Fatal("重放改变数据库、重复记录消息/审计或消耗额度")
			}
		})
	}
}
