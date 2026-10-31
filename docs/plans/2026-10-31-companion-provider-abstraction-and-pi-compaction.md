# 伴学 Agent 多模型供应商抽象与 Pi 式 60% 上下文压缩流控实施计划

> **Goal**: 构建可扩展的 Go 伴学 Agent 多模型供应商抽象架构（对接 2026 最新 DeepSeek 1M 上下文规格与 Ollama/OpenRouter/自定义上游），并在 Python 端实施 NLP 工具高信噪比投影蒸馏，在 Go 端落地 Pi 式动态 Context Window 60% 水位线压缩流控。
> **Tech Stack**: Go 1.24+ (goroutines, context, go-openai), Python 3.11 (FastAPI, spaCy)
> **Spec Reference**: ADR-0025, ADR-0008, Pi-Agent Context Engineering Invariants
> **Global Constraints**: 严禁硬编码固定字符数作为上下文截断阈值；严禁直接转储未经蒸馏的 spaCy 内部指针；活跃 User 提问与正在执行的 Tool 链物理层严禁折叠；零凭证明文落地（遵循 `[REDACTED]` 脱敏纪律）。
> **Branch**: `feat/companion-provider-registry-and-pi-compaction`

---

## [NOTE] 调研与闭环决策 (Research & Closed Decisions)

### 1. 2026 年最新 DeepSeek 官方 API 规约（已物理抓取核实）
- **官方请求入口**:
  - OpenAI 兼容协议 Base URL: `https://api.deepseek.com`
  - Anthropic 兼容协议 Base URL: `https://api.deepseek.com/anthropic`
- **最新生产级主力模型**:
  - `deepseek-flash`（由 DeepSeek-V4.1-Flash-1017 强力驱动，向下兼容 `deepseek-chat` / `deepseek-v4-flash`）
  - `deepseek-v4-pro`（由 DeepSeek-V4-Pro-0813 驱动）
- **上下文与输出配额**:
  - 上下文总长（Context Length）: **1M Tokens** (1,048,576 tokens)
  - 最大输出（Max Output Tokens）: **384K Tokens**
- **原生思考链（Thinking Mode）**:
  - 请求体传参：`thinking: {"type": "enabled"}`, `reasoning_effort: "high"`

### 2. Pi-Agent 上下文流控架构映射
- **废弃静态绝对字符常量**: 摒弃 `DefaultContextMaxChars = 4000/32000`，改为由 `ModelSpec.ContextWindow` 动态计算。
- **60% 压缩警戒线（Compaction Threshold）**: 只有当当前对话累积 Token 超过 `ContextWindow * 0.60` 时，才触发历史折叠。
- **活跃轮次绝对保护**: 倒数第 2 条 User 提示词至末尾的活跃块（包含 User + Assistant ToolCalls + Tool Results）永远完整保留在上下文中。

### 3. 工具高信噪比投影蒸馏（Tool Result Distillation）
- `analyze` 工具（Python 端）执行面向 LLM 的轻量蒸馏投影：剔除 spaCy 底层调试指针（`tag`, `dep`, `head_id`, `is_space` 及 5 场域内部重复的 Token 全量副本），将 13.5KB 的 AST 转储浓缩为 ~400 字节高密度语言学拓扑骨架。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: Python NLP 工具返回值高信噪比蒸馏投影 [Tier: 2-Standard] [Mode: AFK] [Role: Python NLP Builder]
为 `analyze` 等诊断工具引入面向 Agent 的轻量级投影器，消除底层冗余 AST，将单次调用结果压缩 95% 以上。

**Files:**
- Modify: `delector/tools/analyze.py`
- Create: `tests/test_tools_distill.py`

**Interfaces:**
- Consumes: `process_german_text(text: str) -> Dict[str, Any]`
- Produces: `distill_analysis_for_agent(raw_res: Dict[str, Any]) -> Dict[str, Any]`

**Injected Instincts:**
- [ ] `[Instinct: Zero-Information-Loss]`: 蒸馏后必须完整保留 `vorfeld`, `linke_klammer`, `mittelfeld`, `rechte_klammer`, `nachfeld` 原文、`sentence_type`、`bracket_structure` 以及词元的 `text, lemma, pos, case, gender, cefr_level`。
- [ ] `[Instinct: Backward-Compatibility]`: 原有 `process_german_text` 接口保持不变，非 Agent 场景不受影响。

**Subagent Prompt Scaffold:**
> "Implement Task 1: Python NLP 工具返回值高信噪比蒸馏投影.
> Mode: AFK | Role: Python NLP Builder
> Goal: 在 delector/tools/analyze.py 实现 distill_analysis_for_agent 函数，并在 run() 中返回高信噪比字典，将 13KB+ 的原始 AST 压缩至 500 字符以内.
> Target Files: Modify `delector/tools/analyze.py`, Create `tests/test_tools_distill.py`.
> TDD Steps:
> 1. 编写 tests/test_tools_distill.py (RED)，断言 distill_analysis_for_agent 产出保留全部拓扑场域和必要形态，且序列化 JSON 长度 < 800 字符。
> 2. 运行 pytest tests/test_tools_distill.py 确认失败。
> 3. 在 delector/tools/analyze.py 实现蒸馏逻辑并接入 run() (GREEN)。
> 4. 运行 pytest tests/test_tools_distill.py tests/test_tools.py 确认全部通过。
> 5. 抓取物理收据与 JSON 压缩前后对比."

**Step Breakdown:**
- [ ] **Step 1: Write failing test `tests/test_tools_distill.py` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `distill_analysis_for_agent` in `delector/tools/analyze.py` (GREEN)**
- [ ] **Step 4: Run tests and verify green**
- [ ] **Step 5: Physical Evidence Gate**: 记录压缩前后字节对比（~13,500 降至 ~450 字节）与 pytest pass
- [ ] **Step 6: Git atomic commit**

---

### Task 2: Go 伴学 Agent 多模型供应商抽象与注册中心 [Tier: 2-Standard] [Mode: AFK] [Role: Go Architecture Builder]
在 Go 端抽象 `Provider` 接口与 `ModelSpec` 规格字典，预留统一模型接入入口。

**Files:**
- Create: `agent/internal/provider/provider.go`
- Create: `agent/internal/provider/registry.go`
- Create: `agent/internal/provider/registry_test.go`

**Interfaces:**
- Produces: `type Provider interface { ID() string; DisplayName() string; DefaultBaseURL() string; DefaultModel() string; ResolveModelSpec(model string) ModelSpec; CreateClient(apiKey string, baseURL string) (*openai.Client, error) }`
- Produces: `type ModelSpec struct { Name string; ProviderID string; ContextWindow int; MaxOutputTokens int; SupportsToolCalling bool; SupportsThinking bool; CompactionRatio float64 }`
- Produces: `func NewDefaultRegistry() *Registry`

**Injected Instincts:**
- [ ] `[Instinct: 2026-Specs]`: DeepSeek 默认注册 `deepseek-flash` (1M 上下文, 384k 输出) 与 `deepseek-v4-pro` (1M 上下文)，向下兼容 `deepseek-chat`。
- [ ] `[Instinct: Thread-Safe]`: Registry 并发读写使用 `sync.RWMutex` 保证安全。

**Subagent Prompt Scaffold:**
> "Implement Task 2: Go 伴学 Agent 多模型供应商抽象与注册中心.
> Mode: AFK | Role: Go Architecture Builder
> Goal: 在 agent/internal/provider 中创建 Provider 接口、ModelSpec 及 Registry，内置 DeepSeek (1M tokens)、Ollama (32k tokens)、OpenRouter 与 Custom 供应商.
> Target Files: Create `agent/internal/provider/provider.go`, `agent/internal/provider/registry.go`, `agent/internal/provider/registry_test.go`.
> TDD Steps:
> 1. 编写 registry_test.go (RED)，测试供应商注册、模型上下文解析（deepseek-flash 应返回 1048576，qwen3.5:4b 返回 32768）与客户端构建。
> 2. 执行 go test ./internal/provider/... 确认编译/测试失败。
> 3. 实现 provider.go 与 registry.go (GREEN)。
> 4. 执行 go test -v ./internal/provider/... 确认 100% 通过。
> 5. 抓取物理测试收据."

**Step Breakdown:**
- [ ] **Step 1: Write failing test `agent/internal/provider/registry_test.go` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `provider.go` and `registry.go` (GREEN)**
- [ ] **Step 4: Run tests and verify green**
- [ ] **Step 5: Physical Evidence Gate**: 输出 go test 结果与模型规格表映射核验收据
- [ ] **Step 6: Git atomic commit**

---

### Task 3: Pi 式动态上下文 Token 估算与 60% 阈值流控压缩 [Tier: 2-Standard] [Mode: AFK] [Role: Go Agent Builder]
将 `compaction.go` 升级为基于 `ModelSpec` 动态水位的流控引擎，废除固定字符截断，严格执行 60% 水位线压缩。

**Files:**
- Modify: `agent/internal/companion/compaction.go`
- Modify: `agent/internal/companion/compaction_test.go`
- Modify: `agent/internal/companion/compaction_regression_test.go`

**Interfaces:**
- Consumes: `provider.ModelSpec`
- Produces: `func EstimateTokens(messages []openai.ChatCompletionMessage) int`
- Produces: `func CompactMessagesDynamic(messages []openai.ChatCompletionMessage, spec provider.ModelSpec) []openai.ChatCompletionMessage`

**Injected Instincts:**
- [ ] `[Instinct: Pi-Invariant]`: 压缩阈值严格定为 `int(float64(spec.ContextWindow) * spec.CompactionRatio)`（默认 60%）。
- [ ] `[Instinct: Active-Turn-Shield]`: 倒数第 2 条 User 消息往后的活跃轮次任何情况下严禁折叠，即使超限也优先保留活跃 User 意图。

**Subagent Prompt Scaffold:**
> "Implement Task 3: Pi 式动态上下文 Token 估算与 60% 阈值流控压缩.
> Mode: AFK | Role: Go Agent Builder
> Goal: 重构 agent/internal/companion/compaction.go，实现基于 Token 估算与 ModelSpec 的动态 60% 阈值压缩，保障长会话历史平滑折叠且活跃 Tool 链完好.
> Target Files: Modify `agent/internal/companion/compaction.go`, `agent/internal/companion/compaction_test.go`.
> TDD Steps:
> 1. 在 compaction_test.go 编写动态压缩测试 (RED)：在 1M 上下文模型下未达 600k tokens 绝不触发压缩；在小上下文（如 4k tokens）超过 60% (2.4k) 时平滑折叠历史。
> 2. 执行 go test ./internal/companion/... 确认测试失败。
> 3. 实现 Token 估算与 CompactMessagesDynamic (GREEN)。
> 4. 运行 go test ./internal/companion/... 验证全部测试通过。
> 5. 抓取物理测试收据."

**Step Breakdown:**
- [ ] **Step 1: Write failing dynamic compaction test (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `CompactMessagesDynamic` and Token estimation (GREEN)**
- [ ] **Step 4: Run tests and verify green**
- [ ] **Step 5: Physical Evidence Gate**: 输出 60% 阈值触发前后消息拓扑结构
- [ ] **Step 6: Git atomic commit**

---

### Task 4: 伴学 Loop 与 Supervisor / 路由全链路装配 [Tier: 2-Standard] [Mode: AFK] [Role: Full-Stack Integrator]
将 Provider Registry 与动态流控引擎接入 `CompanionAgent` 运行时，打通配置传递。

**Files:**
- Modify: `agent/internal/companion/loop.go`
- Modify: `agent/internal/companion/server.go`
- Modify: `agent/cmd/delector/agent.go`
- Create: `tests/test_companion_provider_integration.py`

**Interfaces:**
- Consumes: `provider.NewDefaultRegistry()`
- Produces: `CompanionAgent` 自适应根据当前请求的 BaseURL 与 Model 解析所属 Provider 与 ModelSpec，驱动动态流控。

**Injected Instincts:**
- [ ] `[Instinct: Zero-Breakage]`: 原有 CLI 参数与 FastAPI 请求头（`X-API-Key`, `X-Base-URL`, `X-Model`）100% 保持向前兼容。
- [ ] `[Instinct: Full-Gate-Clean]`: 四道机械门禁、Go 全量测试、Python 全量测试无告警全绿。

**Subagent Prompt Scaffold:**
> "Implement Task 4: 伴学 Loop 与 Supervisor / 路由全链路装配.
> Mode: AFK | Role: Full-Stack Integrator
> Goal: 在 agent/internal/companion/loop.go 中接入 Provider Registry，实现模型规格自适应与 60% 动态流控，并通过端到端集成测试验证.
> Target Files: Modify `agent/internal/companion/loop.go`, `agent/internal/companion/server.go`, `agent/cmd/delector/agent.go`, Create `tests/test_companion_provider_integration.py`.
> TDD Steps:
> 1. 编写集成测试 tests/test_companion_provider_integration.py 验证多模型配置下反代与 SSE 传输 (RED)。
> 2. 在 loop.go 与 server.go 装配 Registry (GREEN)。
> 3. 运行全景测试：go test ./... 与 pytest 确认 100% PASS。
> 4. 运行四道机械门禁确认 100% PASS。
> 5. 抓取物理执行收据."

**Step Breakdown:**
- [ ] **Step 1: Write integration tests (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Wire Registry into Companion loop and CLI (GREEN)**
- [ ] **Step 4: Run all Go and Python tests and verify green**
- [ ] **Step 5: Run four mechanical gates and verify green**
- [ ] **Step 6: Physical Evidence Gate**: 抓取全景测试通行证与 git diff
- [ ] **Step 7: Git atomic commit & PR landing**

---

## [NOTE] 延期处理项 (Deferred Gap Register)

| gap | why deferred | trigger that forces revisiting | owner |
| :--- | :--- | :--- | :--- |
| Anthropic 原生协议客户端适配 | 当前 DeepSeek 与主流代理已全面支持 OpenAI-compatible 协议，优先保障主线体验 | 用户显式要求接入原生 Claude API 或 Anthropic SDK 时触发 | Provider Infra |
| 视觉模型（Vision）Token 动态折算 | 当前伴学仅处理文本与语法场域，未接入图片解析 | 引入德语试卷/图片直接 OCR 问诊需求时触发 | Vision Multi-modal |

---

## [NOTE] 范围之外 (Out of Scope)

- 自建公网反向代理或公网常驻服务（严格遵守用户零公网运维约束）。
- 前端界面的大型重构（仅保持既有零 `innerHTML` 契约，优先保障后端状态机与流控健全）。
