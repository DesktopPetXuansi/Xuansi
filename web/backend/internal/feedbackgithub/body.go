package feedbackgithub

import "strings"

func issueTitle(in Submission) string {
	title := strings.Join(strings.Fields(in.Title), " ")
	// 标题不支持代码块，移除提及触发字符并限制长度。
	title = strings.ReplaceAll(title, "@", "＠")
	runes := []rune(title)
	if len(runes) > 180 {
		title = string(runes[:180])
	}
	category := in.Category
	if category != "BUG" && category != "SUGGESTION" && category != "OTHER" {
		category = "OTHER"
	}
	return "[" + category + "] " + title
}

func issueBody(in Submission, marker string) string {
	var out strings.Builder
	out.WriteString(marker + "\n\n## 反馈类型\n" + fenced(in.Category) + "\n\n## 标题\n" + fenced(in.Title) + "\n\n## 问题描述\n" + fenced(in.Description))
	// 联系方式仅保留在收件数据库；诊断只接受现有五个固定字段。
	for _, key := range []string{"appVersion", "system", "architecture", "pythonVersion", "qtVersion"} {
		if value := in.Diagnostics[key]; value != "" {
			out.WriteString("\n\n### " + key + "\n" + fenced(value))
		}
	}
	return out.String()
}

// fenced 选择长于内容中连续反引号的围栏，防止提及及 Markdown 指令逃逸。
func fenced(value string) string {
	longest, run := 0, 0
	for _, r := range value {
		if r == '`' {
			run++
			if run > longest {
				longest = run
			}
		} else {
			run = 0
		}
	}
	length := longest + 1
	if length < 3 {
		length = 3
	}
	fence := strings.Repeat("`", length)
	return fence + "\n" + value + "\n" + fence
}
