package registry

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"

	"github.com/ROM4n2/DeLector/agent/internal/pythonsvc"
)

// stubOK 返回恒成功、固定结果的桩 ToolFunc（不经网络）。
func stubOK(result map[string]any) ToolFunc {
	return func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return result, nil
	}
}

// TestRegister_Duplicate 钉住：重名注册被拒（返回错误而非 panic），
// 且首次注册的实现不得被覆盖。
func TestRegister_Duplicate(t *testing.T) {
	r := NewRegistry()
	if err := r.Register("ingest", stubOK(nil)); err != nil {
		t.Fatalf("首次注册不应报错: %v", err)
	}
	err := r.Register("ingest", stubOK(map[string]any{"evil": true}))
	if err == nil {
		t.Fatal("重名注册应被拒绝")
	}
	if !strings.Contains(err.Error(), "ingest") {
		t.Errorf("错误信息应含被拒工具名，实际: %v", err)
	}
	res, runErr := r.Run(context.Background(), "ingest", nil)
	if runErr != nil {
		t.Fatalf("Run(ingest): %v", runErr)
	}
	if _, polluted := res["evil"]; polluted {
		t.Errorf("重名注册不应覆盖首次实现，实际: %v", res)
	}
}

// TestRegister_Guards 钉住：空名与 nil ToolFunc 被卫语句拒绝，
// 被拒注册不得写入表。
func TestRegister_Guards(t *testing.T) {
	r := NewRegistry()
	if err := r.Register("", stubOK(nil)); err == nil {
		t.Error("空工具名应被拒绝")
	}
	if err := r.Register("x", nil); err == nil {
		t.Error("nil ToolFunc 应被拒绝")
	}
	if got := r.List(); len(got) != 0 {
		t.Errorf("被拒注册不得写入表，实际: %v", got)
	}
}

// TestList_Sorted 钉住：List() 返回按字典序排序的名字，
// 空 Registry 返回非 nil 空切片。
func TestList_Sorted(t *testing.T) {
	r := NewRegistry()
	for _, name := range []string{"tts", "analyze", "export", "ingest", "writing_check"} {
		if err := r.Register(name, stubOK(nil)); err != nil {
			t.Fatalf("注册 %s: %v", name, err)
		}
	}
	got := r.List()
	want := []string{"analyze", "export", "ingest", "tts", "writing_check"}
	if !slices.Equal(got, want) {
		t.Errorf("List() = %v，期望排序后 %v", got, want)
	}
	if empty := NewRegistry().List(); empty == nil || len(empty) != 0 {
		t.Errorf("空 Registry.List() = %#v，期望非 nil 空切片", empty)
	}
}

// TestRun_Dispatch 钉住：Run 分发到对应桩，payload 原样透传，
// 桩返回值与错误均原样上抛。
func TestRun_Dispatch(t *testing.T) {
	r := NewRegistry()
	var gotPayload map[string]any
	_ = r.Register("echo", func(_ context.Context, payload map[string]any) (map[string]any, error) {
		gotPayload = payload
		return map[string]any{"ok": true}, nil
	})
	_ = r.Register("boom", func(_ context.Context, _ map[string]any) (map[string]any, error) {
		return nil, errors.New("boom")
	})

	payload := map[string]any{"q": "x"}
	res, err := r.Run(context.Background(), "echo", payload)
	if err != nil {
		t.Fatalf("Run(echo): %v", err)
	}
	if !slices.Equal(mapKeys(gotPayload), mapKeys(payload)) {
		t.Errorf("payload 未原样透传: got %v want %v", gotPayload, payload)
	}
	if gotPayload["q"] != "x" {
		t.Errorf("payload 键值未透传: %v", gotPayload)
	}
	if res["ok"] != true {
		t.Errorf("桩返回值未透传: %v", res)
	}

	if _, err := r.Run(context.Background(), "boom", nil); err == nil || err.Error() != "boom" {
		t.Errorf("工具内部错误应原样上抛，实际: %v", err)
	}
}

// TestRun_Unknown 钉住：未注册名报错，文案对齐 Python 侧 404 detail
// "unknown tool: {name}"（delector/routes/tools.py），
// 且可 errors.Is(err, ErrUnknownTool) 判定（禁字符串比较）。
func TestRun_Unknown(t *testing.T) {
	r := NewRegistry()
	_, err := r.Run(context.Background(), "nope", nil)
	if err == nil {
		t.Fatal("未注册名应报错")
	}
	if !strings.Contains(err.Error(), "unknown tool: nope") {
		t.Errorf("错误文案应对齐 Python 404 detail，实际: %v", err)
	}
	if !errors.Is(err, ErrUnknownTool) {
		t.Errorf("应可 errors.Is(err, ErrUnknownTool) 判定，实际: %v", err)
	}
}

// TestHas 钉住：Has 对已注册/未注册名的判定。
func TestHas(t *testing.T) {
	r := NewRegistry()
	if r.Has("ingest") {
		t.Error("空 Registry 不应 Has 任何名字")
	}
	_ = r.Register("ingest", stubOK(nil))
	if !r.Has("ingest") {
		t.Error("Has(ingest) 应为 true")
	}
	if r.Has("nope") {
		t.Error("Has(nope) 应为 false")
	}
}

// TestDefaultRegistry_Golden 防漂移哨兵：DefaultRegistry 的 List() 必须恰为
// Python 侧 delector/tools/__init__.py 的 TOOL_REGISTRY 实况
// （ingest / analyze / writing_check / export / tts；ADR-0009 后
// exercise 已更名 writing_check）。任何一侧工具清单变更，必须同步
// ADR-0008 工具表与本测试。
func TestDefaultRegistry_Golden(t *testing.T) {
	// 不经网络：仅构造 Client（baseURL 指向不可达回环，无请求发出）。
	c := pythonsvc.NewClient("http://127.0.0.1:1", nil)
	got := DefaultRegistry(c).List()
	want := []string{"analyze", "export", "ingest", "tts", "writing_check"}
	if !slices.Equal(got, want) {
		t.Errorf("DefaultRegistry().List() = %v，期望与 delector/tools/__init__.py TOOL_REGISTRY 对齐的 %v", got, want)
	}
}

// TestDefaultRegistry_WrapsRunTool 钉住：DefaultRegistry 的 5 个工具均为
// c.RunTool 的薄包装（闭包固定 name，各自分发到正确的 /api/tools/{name}），
// 全程走 httptest 本地桩，不触真实 Python 实例。
func TestDefaultRegistry_WrapsRunTool(t *testing.T) {
	called := map[string]int{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called[r.URL.Path]++
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()

	reg := DefaultRegistry(pythonsvc.NewClient(srv.URL, srv.Client()))
	for _, name := range reg.List() {
		if _, err := reg.Run(context.Background(), name, nil); err != nil {
			t.Fatalf("Run(%s): %v", name, err)
		}
	}
	if len(called) != len(reg.List()) {
		t.Errorf("应恰有 %d 个不同路径被调用，实际: %v", len(reg.List()), called)
	}
	for _, name := range reg.List() {
		if called["/api/tools/"+name] != 1 {
			t.Errorf("工具 %s 应恰好分发到 /api/tools/%s 一次，实际调用分布: %v", name, name, called)
		}
	}
}

// mapKeys 返回 map 的键切片（测试辅助，供逐键比较）。
func mapKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}
