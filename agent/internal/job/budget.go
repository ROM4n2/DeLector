package job

import (
	"errors"
	"sync"
)

// ErrBudgetExceeded 表示一次 Reserve 会把 TokenBudget 的已用额度推出 cap 上限。
// 通过 errors.Is 判定，供调用方（如 runner 预算耗尽降级）识别。
var ErrBudgetExceeded = errors.New("job: token budget exceeded")

// TokenBudget 是对 DeepSeek 真调用 token 消耗的成本护栏：多个并发步骤共享
// 同一实例，Reserve 在并发下原子递增。cap<=0 表示不设上限（无限）。
type TokenBudget struct {
	mu   sync.Mutex
	cap  int
	used int
}

// NewTokenBudget 构造预算上限为 cap 的 TokenBudget。cap<=0 表示无限额度。
func NewTokenBudget(cap int) *TokenBudget {
	return &TokenBudget{cap: cap}
}

// Reserve 预留 est 个 token（est 由调用方按文本长度估算）。语义：
//   - est<0 视为非法，返回错误且不影响 used；
//   - cap>0 且 used+est>cap 时返回 ErrBudgetExceeded，used 不变；
//   - cap<=0 视为无限，总接受；
//   - 成功时 used 原子 +est。
//
// 并发安全：同一实例可被多个 goroutine 同时 Reserve。
func (b *TokenBudget) Reserve(est int) error {
	if est < 0 {
		return errors.New("job: token budget reserve est 不能为负")
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.cap > 0 && b.used+est > b.cap {
		return ErrBudgetExceeded
	}
	b.used += est
	return nil
}

// Used 返回当前已预留 token 数。并发安全。
func (b *TokenBudget) Used() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.used
}
