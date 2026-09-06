package pythonsvc

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"
)

// ErrToolNotFound 哨兵错误：Python 侧 TOOL_REGISTRY 无此工具名（HTTP 404）。
// 调用方以 errors.Is(err, ErrToolNotFound) 判定，禁字符串比较。
var ErrToolNotFound = errors.New("pythonsvc: tool not found")

// defaultTimeout 为 Client 默认 HTTP 超时，覆盖 Python 侧最慢工具
// （ingest 拉外网、tts 合成）的最坏耗时。
const defaultTimeout = 120 * time.Second

// ToolError 映射 Python 侧 HTTP 400：tool.run 抛异常时 FastAPI 返回
// {"detail": "<name> failed: <exc>"}（见 delector/routes/tools.py）。
// Detail 为服务端 detail 原文，Error() 输出可读串。
type ToolError struct {
	Name   string
	Detail string
}

// Error 返回包含工具名与服务端 detail 的可读错误串。
func (e *ToolError) Error() string {
	return fmt.Sprintf("pythonsvc: tool %q failed: %s", e.Name, e.Detail)
}

// Client 封装 Python NLP 微服务的 POST /api/tools/{name} 契约。
// 零值不可用，经 NewClient 构造。
type Client struct {
	baseURL string
	hc      *http.Client
}

// NewClient 构造 Client；hc 为 nil 时使用默认 &http.Client{Timeout: 120s}，
// 测试可注入自定义 *http.Client（如 httptest 的 srv.Client()）。
func NewClient(baseURL string, hc *http.Client) *Client {
	if hc == nil {
		hc = &http.Client{Timeout: defaultTimeout}
	}
	return &Client{baseURL: baseURL, hc: hc}
}

// RunTool 调用 POST {baseURL}/api/tools/{name}，body 为 {"payload": {...}}，
// Content-Type application/json。payload 为 nil 时按 Python 侧 pydantic
// 默认值归一为空 dict。
//
// 错误映射（契约见 delector/routes/tools.py）：
//   - 200 → 解析 JSON 为 map[string]any 返回
//   - 404 → 哨兵 ErrToolNotFound
//   - 400 → *ToolError（Detail 为服务端 detail 原文）
//   - 403 → 错误信息含 localhost 提示（_require_localhost 闸）
//   - 其余状态码 → 含状态码的通用错误
//
// 全部请求经 NewRequestWithContext：调用方 ctx 超时/取消的错误链以 %w
// 保留，可用 errors.Is(err, context.DeadlineExceeded) 判定。
func (c *Client) RunTool(ctx context.Context, name string, payload map[string]any) (map[string]any, error) {
	if name == "" {
		return nil, errors.New("pythonsvc: tool name must not be empty")
	}
	if payload == nil {
		payload = map[string]any{}
	}

	callBody, err := json.Marshal(map[string]any{"payload": payload})
	if err != nil {
		return nil, fmt.Errorf("pythonsvc: encode payload of tool %q: %w", name, err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.toolURL(name), bytes.NewReader(callBody))
	if err != nil {
		return nil, fmt.Errorf("pythonsvc: build request of tool %q: %w", name, err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("pythonsvc: call tool %q: %w", name, err)
	}
	defer resp.Body.Close()

	switch resp.StatusCode {
	case http.StatusOK:
		var result map[string]any
		if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
			return nil, fmt.Errorf("pythonsvc: decode response of tool %q: %w", name, err)
		}
		return result, nil
	case http.StatusNotFound:
		return nil, fmt.Errorf("pythonsvc: call tool %q: %w (detail: %s)", name, ErrToolNotFound, detailOf(resp))
	case http.StatusBadRequest:
		return nil, &ToolError{Name: name, Detail: detailOf(resp)}
	case http.StatusForbidden:
		return nil, fmt.Errorf("pythonsvc: tool %q is restricted to localhost (403): %s", name, detailOf(resp))
	default:
		return nil, fmt.Errorf("pythonsvc: tool %q: unexpected status %d: %s", name, resp.StatusCode, detailOf(resp))
	}
}

// toolURL 拼接 {baseURL}/api/tools/{name}，name 经路径转义。
func (c *Client) toolURL(name string) string {
	return c.baseURL + "/api/tools/" + url.PathEscape(name)
}

// detailOf 读取 FastAPI 错误响应体 {"detail": ...} 的 detail 字符串；
// 解析失败返回空串（不掩盖原始状态码信息）。
func detailOf(resp *http.Response) string {
	var body struct {
		Detail string `json:"detail"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return ""
	}
	return body.Detail
}
