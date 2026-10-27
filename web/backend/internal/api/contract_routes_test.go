package api

import (
	"encoding/json"
	"net/http"
	"os"
	"slices"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"xuansi/web/backend/internal/oauth"
)

type contractParameter struct {
	Name        string          `json:"name"`
	In          string          `json:"in"`
	Required    bool            `json:"required"`
	Description string          `json:"description"`
	Schema      json.RawMessage `json:"schema"`
}

type contractOperation struct {
	Parameters []contractParameter   `json:"parameters"`
	Security   []map[string][]string `json:"security"`
	Responses  map[string]struct {
		Content map[string]json.RawMessage `json:"content"`
	} `json:"responses"`
}

func loadRouteContract(t *testing.T) map[string]map[string]contractOperation {
	t.Helper()
	payload, err := os.ReadFile("../../../contracts/openapi.yaml")
	if err != nil {
		t.Fatal(err)
	}
	var document struct {
		Paths map[string]map[string]contractOperation `json:"paths"`
	}
	if err = json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	if len(document.Paths) == 0 {
		t.Fatal("OpenAPI 没有可校验的路径")
	}
	return document.Paths
}

// 直接遍历真实 Router，新增路由漏记或契约残留不存在的接口都会失败。
func TestContractRoutesMatchRouter(t *testing.T) {
	contract := loadRouteContract(t)
	server := &Server{OAuth: &oauth.Service{}}
	routes := server.Router().(chi.Routes)
	actual := map[string]bool{}
	if err := chi.Walk(routes, func(method, path string, _ http.Handler, _ ...func(http.Handler) http.Handler) error {
		// chi Mount 同时接收子根的无斜杠路径，Walk 则把子根列成末尾斜杠形式。
		path = strings.TrimSuffix(path, "/")
		actual[method+" "+path] = true
		if _, exists := contract[path][strings.ToLower(method)]; !exists {
			t.Errorf("真实接口未进入契约：%s %s", method, path)
		}
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	declared := 0
	for path, operations := range contract {
		for method := range operations {
			if !slices.Contains([]string{"get", "post", "put", "patch", "delete", "head", "options", "trace"}, method) {
				continue
			}
			declared++
			if !actual[strings.ToUpper(method)+" "+path] {
				t.Errorf("契约声明了不存在的接口：%s %s", method, path)
			}
		}
	}
	t.Logf("已双向核对真实路由 %d 项、契约操作 %d 项（含 OAuth 和健康探针）", len(actual), declared)
}

// 查询参数是公开能力，不把其他列表的通用参数误宣称成已实现筛选。
func TestContractQueryParameters(t *testing.T) {
	contract := loadRouteContract(t)
	// 仅列真实读取并生效的参数；其余操作默认不提供查询能力。
	expectedQueries := map[string][]string{
		"GET /api/v1/resources":                    {"cursor", "group", "kind", "limit", "search", "tag"},
		"GET /api/v1/me/resources":                 {"cursor", "group", "kind", "limit", "search", "tag"},
		"GET /api/v1/client/releases":              {"arch", "channel", "os"},
		"GET /api/v1/client/releases/latest":       {"arch", "channel", "os"},
		"GET /api/v1/client/releases/{id}":         {"arch", "channel", "os"},
		"GET /api/v1/admin/users":                  {"cursor", "limit", "role", "search", "status"},
		"GET /api/v1/admin/resources":              {"limit"},
		"GET /api/v1/me/history":                   {"cursor", "kind", "limit"},
		"DELETE /api/v1/me/history":                {"kind"},
		"GET /api/v1/admin/feedback":               {"cursor", "folder", "limit", "status"},
		"GET /api/v1/admin/feedback/{id}/messages": {"cursor", "limit"},
		"GET /api/v1/me/feedback":                  {"cursor", "limit", "status"},
		"GET /api/v1/me/feedback/{id}/messages":    {"cursor", "limit"},
		"GET /api/v1/admin/feedback/conversations": {"cursor", "limit", "status"},
		"GET /oauth/authorize":                     {"client_id", "code_challenge", "code_challenge_method", "redirect_uri", "response_type", "scope", "state"},
	}
	checked := 0
	for path, operations := range contract {
		for method, operation := range operations {
			if !slices.Contains([]string{"get", "post", "put", "patch", "delete", "head", "options", "trace"}, method) {
				continue
			}
			name := strings.ToUpper(method) + " " + path
			checked++
			t.Run(name, func(t *testing.T) {
				var query []string
				for _, parameter := range operation.Parameters {
					if parameter.In == "query" {
						query = append(query, parameter.Name)
					}
				}
				slices.Sort(query)
				if expected := expectedQueries[name]; !slices.Equal(query, expected) {
					t.Errorf("查询参数应为 %v，实际为 %v", expected, query)
				}
			})
		}
	}
	t.Logf("已校验全部 %d 个操作的查询参数，只有 %d 个操作声明实际查询能力", checked, len(expectedQueries))
}

// 图片和 ZIP 是原始字节，不能让生成客户端误按 JSON envelope 解析。
func TestContractBinaryResponses(t *testing.T) {
	contract := loadRouteContract(t)
	for path, mediaType := range map[string]string{
		"/api/v1/resources/{id}/cover": "image/png",
		"/api/v1/downloads/{ticket}":   "application/zip",
	} {
		t.Run(path, func(t *testing.T) {
			content := contract[path]["get"].Responses["200"].Content
			if _, exists := content[mediaType]; !exists || len(content) != 1 {
				t.Errorf("成功响应必须是 %s 原始字节，实际为 %v", mediaType, content)
			}
		})
	}
}

// 垃圾箱复用已有列表，清空操作必须明确网站会话与 CSRF 边界。
func TestContractFeedbackSpam(t *testing.T) {
	contract := loadRouteContract(t)
	var folder *contractParameter
	for _, parameter := range contract["/api/v1/admin/feedback"]["get"].Parameters {
		if parameter.In == "query" && parameter.Name == "folder" {
			folder = &parameter
		}
	}
	var schema struct {
		Enum    []string `json:"enum"`
		Default string   `json:"default"`
	}
	if folder == nil || json.Unmarshal(folder.Schema, &schema) != nil || schema.Default != "inbox" || !slices.Equal(schema.Enum, []string{"inbox", "spam"}) {
		t.Fatal("反馈列表必须声明默认收件箱和独立垃圾箱分区")
	}
	operation := contract["/api/v1/admin/feedback/spam"]["delete"]
	if len(operation.Security) != 1 {
		t.Fatal("垃圾箱清空只能使用网站管理员会话")
	}
	if _, exists := operation.Security[0]["cookieAuth"]; !exists || len(operation.Security[0]) != 1 {
		t.Fatal("垃圾箱清空不能继承桌面 Bearer 授权")
	}
	for _, parameter := range operation.Parameters {
		if parameter.In == "header" && parameter.Name == "X-CSRF-Token" && parameter.Required {
			t.Log("垃圾箱筛选、网站会话和必需 CSRF 契约校验通过")
			return
		}
	}
	t.Fatal("垃圾箱清空必须声明必需的 CSRF 请求头")
}

// Cookie 写入仍强制 CSRF；允许 Bearer 的操作必须表达条件要求而非一律必传。
func TestContractBearerCSRFIsConditional(t *testing.T) {
	contract := loadRouteContract(t)
	checked := 0
	for path, operations := range contract {
		for method, operation := range operations {
			bearer := false
			for _, security := range operation.Security {
				if _, exists := security["bearerAuth"]; exists {
					bearer = true
				}
			}
			if !bearer {
				continue
			}
			for _, parameter := range operation.Parameters {
				if parameter.In != "header" || parameter.Name != "X-CSRF-Token" {
					continue
				}
				checked++
				if parameter.Required || !strings.Contains(parameter.Description, "Bearer") || !strings.Contains(parameter.Description, "Cookie") {
					t.Errorf("%s %s 的 CSRF 必须说明 Cookie 必需、有效 Bearer 豁免", method, path)
				}
			}
		}
	}
	if checked == 0 {
		t.Fatal("没有校验到允许 Bearer 的 CSRF 参数")
	}
	t.Logf("已校验 %d 个允许 Bearer 的操作之条件 CSRF 契约", checked)
}
