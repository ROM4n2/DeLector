package companion

import "strings"

// 设置页四档 -> 上游 reasoning_effort 的映射。
//
// 依据 DeepSeek 官方 Chat Completions 文档（2026-11-07 核对）：合法值为
// none / low / high / max，`none` 关闭思考；上游会把 medium / xhigh 映射为 high。
// 若把设置页的 medium 原样透传，会与「深度」档落到同一上游强度，四档不可区分，
// 故这里显式映射为四个不同取值：
//
//	关闭 none   -> none
//	极速 low    -> low
//	平衡 medium -> high（上游默认强度）
//	深度 high   -> max
const (
	ReasoningEffortNone = "none"
	ReasoningEffortLow  = "low"
	ReasoningEffortHigh = "high"
	ReasoningEffortMax  = "max"

	// DefaultReasoningEffort 是设置页缺省档位（平衡）。
	DefaultReasoningEffort = "medium"
)

// MapReasoningEffort 把设置页档位映射为上游 reasoning_effort；未知/缺省按「平衡」处理。
func MapReasoningEffort(effort string) string {
	switch strings.ToLower(strings.TrimSpace(effort)) {
	case "none":
		return ReasoningEffortNone
	case "low":
		return ReasoningEffortLow
	case "high":
		return ReasoningEffortMax
	default:
		return ReasoningEffortHigh
	}
}
