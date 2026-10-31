package companion

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// TurnTraceRecord 记录单轮伴学对话执行的元数据与指标。
type TurnTraceRecord struct {
	SessionID       string `json:"session_id,omitempty"`
	Turn            int    `json:"turn"`
	Model           string `json:"model"`
	ReasoningEffort string `json:"reasoning_effort,omitempty"`
	DurationMs      int64  `json:"duration_ms"`
	TokensIn        int    `json:"tokens_in"`
	TokensOut       int    `json:"tokens_out"`
	ToolCount       int    `json:"tool_count"`
	Timestamp       string `json:"timestamp"`
}

var (
	traceMu       sync.Mutex
	traceFilePath = filepath.Clean(os.TempDir() + "/companion_trace.jsonl")
)

// DefaultTracePath 返回默认追踪日志文件路径。
func DefaultTracePath() string {
	return filepath.Clean(os.TempDir() + "/companion_trace.jsonl")
}

// SetTraceFilePath 自定义或重定向追踪日志文件路径（主要用于单元测试与环境隔离）。
func SetTraceFilePath(p string) {
	traceMu.Lock()
	defer traceMu.Unlock()
	traceFilePath = p
}

// GetTraceFilePath 获取当前追踪日志文件路径。
func GetTraceFilePath() string {
	traceMu.Lock()
	defer traceMu.Unlock()
	return traceFilePath
}

// ResetTraceFilePath 重置追踪日志路径为系统默认。
func ResetTraceFilePath() {
	traceMu.Lock()
	defer traceMu.Unlock()
	traceFilePath = DefaultTracePath()
}

// LogTurnTrace 以 JSONL 格式安全追加写入单轮执行追踪记录。
func LogTurnTrace(record TurnTraceRecord) {
	traceMu.Lock()
	defer traceMu.Unlock()

	if record.Timestamp == "" {
		record.Timestamp = time.Now().UTC().Format(time.RFC3339)
	}

	data, err := json.Marshal(record)
	if err != nil {
		return
	}
	data = append(data, '\n')

	target := traceFilePath
	if target == "" {
		target = DefaultTracePath()
	}

	if dir := filepath.Dir(target); dir != "" && dir != "." {
		_ = os.MkdirAll(dir, 0755)
	}

	f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		return
	}
	defer f.Close()

	_, _ = f.Write(data)
}
