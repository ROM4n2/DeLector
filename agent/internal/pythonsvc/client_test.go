package pythonsvc

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// TestRunTool 表驱动钉住 POST /api/tools/{name} 契约（Python 实况，
// 见 delector/routes/tools.py 与 delector/core/database.py 的
// _require_localhost）：200 dict / 404 unknown tool / 400 detail /
// 403 非 localhost / 调用方 ctx 超时必须可
// errors.Is(err, context.DeadlineExceeded) 判定（禁字符串比较）。
func TestRunTool(t *testing.T) {
	tests := []struct {
		name       string         // 子测试名
		toolName   string         // RunTool 的 name 入参
		payload    map[string]any // RunTool 的 payload 入参；nil 钉住归一行为
		stubStatus int            // 桩返回状态码
		stubBody   string         // 桩返回响应体（FastAPI 错误形状 {"detail": ...}）
		stubDelay  time.Duration  // 桩延迟（超时用例）
		ctxTimeout time.Duration  // 测试 ctx 超时；0 表示不设
		checkReq   bool           // 是否断言请求形状（方法/路径/包装体）
		assert     func(t *testing.T, res map[string]any, err error)
	}{
		{
			name:       "200: 响应 JSON 解析为 map 返回",
			toolName:   "analyze",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusOK,
			stubBody:   `{"score": 0.87, "summary": "ok"}`,
			checkReq:   true,
			assert: func(t *testing.T, res map[string]any, err error) {
				if err != nil {
					t.Fatalf("期望成功，实际错误: %v", err)
				}
				if got, ok := res["score"].(float64); !ok || got != 0.87 {
					t.Errorf("res[\"score\"] = %#v，期望 0.87", res["score"])
				}
				if got, ok := res["summary"].(string); !ok || got != "ok" {
					t.Errorf("res[\"summary\"] = %#v，期望 \"ok\"", res["summary"])
				}
			},
		},
		{
			name:     "payload=nil: 归一为空 dict，请求体恰为 {\"payload\":{}}",
			toolName: "analyze",
			// payload 故意省略（nil）：钉住 RunTool 的 nil 归一行为，
			// 对齐 Python 侧 call.payload or {} 的缺省语义（routes/tools.py）。
			stubStatus: http.StatusOK,
			stubBody:   `{}`,
			checkReq:   true,
			assert: func(t *testing.T, _ map[string]any, err error) {
				if err != nil {
					t.Fatalf("期望成功，实际错误: %v", err)
				}
			},
		},
		{
			name:       "404: 未知工具 → ErrToolNotFound",
			toolName:   "nope",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusNotFound,
			stubBody:   `{"detail": "unknown tool: nope"}`,
			assert: func(t *testing.T, _ map[string]any, err error) {
				if err == nil {
					t.Fatal("期望错误，实际成功")
				}
				if !errors.Is(err, ErrToolNotFound) {
					t.Errorf("期望 errors.Is(err, ErrToolNotFound)，实际: %v", err)
				}
			},
		},
		{
			name:       "400: 工具执行失败 → *ToolError 含服务端 detail",
			toolName:   "analyze",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusBadRequest,
			stubBody:   `{"detail": "analyze failed: boom"}`,
			assert: func(t *testing.T, _ map[string]any, err error) {
				var te *ToolError
				if !errors.As(err, &te) {
					t.Fatalf("期望 *ToolError，实际 %T: %v", err, err)
				}
				if te.Detail != "analyze failed: boom" {
					t.Errorf("ToolError.Detail = %q，期望服务端 detail 原文", te.Detail)
				}
				if !strings.Contains(te.Error(), "analyze failed: boom") {
					t.Errorf("ToolError.Error() 应包含服务端 detail，实际: %v", te)
				}
			},
		},
		{
			name:       "403: 非 localhost 闸 → 错误含 localhost 提示",
			toolName:   "export",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusForbidden,
			stubBody:   `{"detail": "该接口仅允许本机访问"}`,
			assert: func(t *testing.T, _ map[string]any, err error) {
				if err == nil {
					t.Fatal("期望错误，实际成功")
				}
				if !strings.Contains(err.Error(), "localhost") {
					t.Errorf("403 错误信息应包含 localhost 提示，实际: %v", err)
				}
				// detail 透传钉板：服务端 detail 原文不得被丢弃。
				if !strings.Contains(err.Error(), "该接口仅允许本机访问") {
					t.Errorf("403 错误信息应透传服务端 detail 原文，实际: %v", err)
				}
			},
		},
		{
			name:       "ctx 超时: 桩延迟超过 ctx 截止 → errors.Is(context.DeadlineExceeded)",
			toolName:   "analyze",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusOK,
			stubBody:   `{}`,
			stubDelay:  300 * time.Millisecond,
			ctxTimeout: 50 * time.Millisecond,
			assert: func(t *testing.T, _ map[string]any, err error) {
				if err == nil {
					t.Fatal("期望超时错误，实际成功")
				}
				if !errors.Is(err, context.DeadlineExceeded) {
					t.Errorf("错误应可 errors.Is(err, context.DeadlineExceeded)，实际: %v", err)
				}
			},
		},
		{
			name:       "空工具名: 卫语句直接报错（不出网）",
			toolName:   "",
			payload:    map[string]any{"q": "x"},
			stubStatus: http.StatusOK,
			stubBody:   `{}`,
			assert: func(t *testing.T, _ map[string]any, err error) {
				if err == nil {
					t.Fatal("空 name 应被卫语句拒绝")
				}
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if tt.stubDelay > 0 {
					time.Sleep(tt.stubDelay)
				}
				// checkReq 用例顺带钉住请求契约：POST /api/tools/{name}，
				// body 为 {"payload": {...}} 包装，Content-Type 为 application/json。
				if tt.checkReq {
					if r.Method != http.MethodPost {
						t.Errorf("请求方法 = %s，期望 POST", r.Method)
					}
					if want := "/api/tools/" + tt.toolName; r.URL.Path != want {
						t.Errorf("请求路径 = %s，期望 %s", r.URL.Path, want)
					}
					if ct := r.Header.Get("Content-Type"); ct != "application/json" {
						t.Errorf("Content-Type = %q，期望 application/json", ct)
					}
					raw, err := io.ReadAll(r.Body)
					if err != nil {
						t.Errorf("读取请求体失败: %v", err)
					} else if tt.payload == nil {
						// payload=nil 钉板：必须归一为空 dict，序列化恰为
						// {"payload":{}}（对齐 Python 侧 call.payload or {}）。
						if string(raw) != `{"payload":{}}` {
							t.Errorf("payload=nil 请求体 = %s，期望 {\"payload\":{}}", raw)
						}
					} else {
						var call struct {
							Payload map[string]any `json:"payload"`
						}
						if err := json.NewDecoder(bytes.NewReader(raw)).Decode(&call); err != nil {
							t.Errorf("请求体解码失败: %v", err)
						} else if call.Payload["q"] != "x" {
							t.Errorf("payload 应原样包装在 {\"payload\": ...}，实际: %v", call.Payload)
						}
					}
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(tt.stubStatus)
				_, _ = w.Write([]byte(tt.stubBody))
			}))
			defer srv.Close()

			ctx := context.Background()
			if tt.ctxTimeout > 0 {
				var cancel context.CancelFunc
				ctx, cancel = context.WithTimeout(ctx, tt.ctxTimeout)
				defer cancel()
			}

			// srv.Client() 无自带超时：确保超时判定来自调用方 ctx 而非 http.Client。
			c := NewClient(srv.URL, srv.Client())
			res, err := c.RunTool(ctx, tt.toolName, tt.payload)
			tt.assert(t, res, err)
		})
	}
}
