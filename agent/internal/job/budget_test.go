package job

import (
	"errors"
	"fmt"
	"sync"
	"testing"
)

func TestTokenBudget_WithinCap(t *testing.T) {
	b := NewTokenBudget(100)
	for _, est := range []int{10, 20, 30} {
		if err := b.Reserve(est); err != nil {
			t.Fatalf("Reserve(%d) 应在预算内：%v", est, err)
		}
	}
	if got := b.Used(); got != 60 {
		t.Fatalf("Used 应累计 60，实得 %d", got)
	}
}

func TestTokenBudget_ReserveExactCapOK(t *testing.T) {
	b := NewTokenBudget(100)
	if err := b.Reserve(100); err != nil {
		t.Fatalf("Reserve 恰达 cap 应成功：%v", err)
	}
	if got := b.Used(); got != 100 {
		t.Fatalf("Used 应为 100，实得 %d", got)
	}
}

func TestTokenBudget_ExceedsCap(t *testing.T) {
	b := NewTokenBudget(100)
	if err := b.Reserve(60); err != nil {
		t.Fatalf("Reserve(60): %v", err)
	}
	// 超 cap：used+est > cap。
	err := b.Reserve(41)
	if !errors.Is(err, ErrBudgetExceeded) {
		t.Fatalf("超 cap 应返回 ErrBudgetExceeded，实得 %v", err)
	}
	// Used 不应因失败而增加。
	if got := b.Used(); got != 60 {
		t.Fatalf("失败 Reserve 后 Used 不应变，期望 60，实得 %d", got)
	}
}

func TestTokenBudget_CapZeroUnlimited(t *testing.T) {
	b := NewTokenBudget(0) // cap 0 = 无限
	for _, est := range []int{1 << 20, 1 << 20, 1 << 20} {
		if err := b.Reserve(est); err != nil {
			t.Fatalf("cap 0（无限）Reserve(%d) 不应失败：%v", est, err)
		}
	}
	if got := b.Used(); got != 3*(1<<20) {
		t.Fatalf("Used 应累计 3*2^20，实得 %d", got)
	}
}

func TestTokenBudget_NegativeEstRejected(t *testing.T) {
	b := NewTokenBudget(100)
	err := b.Reserve(-5)
	if err == nil {
		t.Fatalf("负 est 应被拒")
	}
	if got := b.Used(); got != 0 {
		t.Fatalf("负 est 不应计入 Used，实得 %d", got)
	}
}

// TestTokenBudget_ParallelReserveNoLostUpdates 并发 Reserve 原子性：
// N 个 goroutine 各 reserve 1，总数 ≤ cap 应全成功，且最终 Used==N（无 lost update）。
func TestTokenBudget_ParallelReserveNoLostUpdates(t *testing.T) {
	const (
		cap = 1000
		n   = 300 // 每 goroutine reserve 1 → 总数 300 ≤ cap
	)
	b := NewTokenBudget(cap)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var failed int
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := b.Reserve(1); err != nil {
				mu.Lock()
				failed++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if failed != 0 {
		t.Fatalf("并发 Reserve 应全部成功，实得 %d 失败", failed)
	}
	if got := b.Used(); got != n {
		t.Fatalf("并发 Reserve 无 lost update：期望 Used=%d，实得 %d", n, got)
	}
}

// TestTokenBudget_ParallelReserveHonorsCap 并发下总额不超 cap：
// 大批 goroutine 各 reserve 1，cap 有限时只允许前 cap 个成功，成功数恰好 == cap。
func TestTokenBudget_ParallelReserveHonorsCap(t *testing.T) {
	const (
		cap = 500
		n   = 5000
	)
	b := NewTokenBudget(cap)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var okCount int
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := b.Reserve(1); err == nil {
				mu.Lock()
				okCount++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if okCount != cap {
		t.Fatalf("并发总额不应超 cap：成功 %d，期望恰为 cap=%d", okCount, cap)
	}
	if got := b.Used(); got != cap {
		t.Fatalf("Used 应恰为 cap=%d，实得 %d", cap, got)
	}
}

func ExampleTokenBudget() {
	b := NewTokenBudget(10)
	fmt.Println(b.Reserve(10))                     // 恰达 cap → ok
	err := b.Reserve(5)                            // 10+5>10 → 超限
	fmt.Println(err)                               // 文案
	fmt.Println(errors.Is(err, ErrBudgetExceeded)) // errors.Is 可判定
	fmt.Println(b.Used())                          // 失败不影响 used
	// Output:
	// <nil>
	// job: token budget exceeded
	// true
	// 10
}
