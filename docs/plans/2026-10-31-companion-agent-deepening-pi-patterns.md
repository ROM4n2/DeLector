# 伴学 Agent 深化实施计划：对标 Pi 与工业级智能体自愈流控架构

> **Goal**: 将伴学 Agent 对齐 Pi-Agent 与一线工业级智能体前沿工程设计，落地 Errors-as-Messages 自治自愈闭环、Turn 间主动上下文压缩流控、以及云端-本地双模型级联热备机制。
> **Tech Stack**: Go 1.24+ / 1.26, go-openai v1.43.0, FastAPI, Python 3.11+
> **Spec Reference**: `docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md` · `08-Projects/Pi-Agent/GOTCHAS.md` · `hybrid-agent-runtime`
> **Global Constraints**: Zero innerHTML, 测试严禁真实出网（100% httptest / MockTransport 隔离）, 四道机械门禁 100% 全绿，Go 单测 100% 全绿。
> **Branch**: `feat/companion-study-agent`

---

## [NOTE] Decisions So Far
- [ADR-0010 / ADR-0025](docs/adr/2026-10-31-adr-0025-companion-agent-native-tool-calling-and-streaming.md): Go 作为 Agent Runtime 统一编排中枢，Python 作为领域算法与本地微服务。
- [Pi-Agent GOTCHAS §1.2](08-Projects/Pi-Agent/GOTCHAS.md): 确立 **Errors-as-Messages 原则**（工具异常不中断 Agent Loop，转为 Tool 消息送回模型自愈）。
- [Pi-Agent GOTCHAS §1.4](08-Projects/Pi-Agent/GOTCHAS.md): 确立 **Turn 间主动上下文压缩**（Turn 结束时主动流控，而非等硬截断 OOM）。

---

## [NOTE] Active Frontier (Unblocked Tasks)

### Task 1: Errors-as-Messages 工具自治自愈闭环 [Tier: 2-Standard] [Mode: AFK] [Role: Go TDD Builder]

**Files:**
- Modify: `agent/internal/companion/loop.go:210-250`
- Test: `agent/internal/companion/loop_test.go`

**Interfaces:**
- Consumes: `ToolRunner.RunTool(ctx, name, payload) (map[string]any, error)`
- Produces: 
  - 当工具执行失败或返回错误时，格式化为结构化自愈反馈：
    `{"status": "error", "error_code": "TOOL_EXECUTION_FAILED", "tool": name, "message": err.Error()}`
  - 作为 `openai.ChatMessageRoleTool` 送入上下文，驱动模型在下一轮反思调整参数或向用户解释，绝不向客户端抛出致命 `stream_error`。

**Injected Instincts:**
- [ ] `[Instinct: Self-Healing]`: 工具错误转化为消息反馈模型；仅当所有重试轮次耗尽或模型放弃时才结束当前 Turn。

**Subagent Prompt Scaffold:**
> "Implement Task 1: Errors-as-Messages tool self-healing loop in agent/internal/companion/loop.go.
> Mode: AFK | Role: Go TDD Builder
> Goal: Transform tool execution errors into ChatMessageRoleTool feedback instead of terminating the loop, allowing the model to recover autonomously.
> Target Files: Modify agent/internal/companion/loop.go, Test agent/internal/companion/loop_test.go.
> TDD Steps:
> 1. Add failing test TestCompanionLoopToolErrorSelfHealing in loop_test.go (RED).
> 2. Implement error wrapping and recovery in loop.go (GREEN).
> 3. Verify exit 0 with go test -v ./internal/companion/...
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `agent/internal/companion/loop_test.go` (RED)**: 模拟 Python 微服务首次报语法解析异常，模型在第二轮收到错误消息后成功降级给出提示。
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement minimal production code in `agent/internal/companion/loop.go` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Physical Evidence Gate**: `go test -v ./internal/companion/...` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 2: Turn 间主动上下文流控与滑动窗口压缩器 [Tier: 2-Standard] [Mode: AFK] [Role: Go TDD Builder]

**Files:**
- Create: `agent/internal/companion/compaction.go`
- Test: `agent/internal/companion/compaction_test.go`
- Modify: `agent/internal/companion/loop.go`

**Interfaces:**
- Produces: `func CompactMessages(messages []openai.ChatCompletionMessage, maxChars int) []openai.ChatCompletionMessage`
- 压缩策略：
  - 恒保留 System Prompt（含当前视口学习上下文）；
  - 恒保留最近的 2 轮（4 消息）完整问答；
  - 中间过长的历史轮次（若总长度超过 `maxChars`，默认 4000 字符），压缩为一条单行状态锚点：
    `Role: system, Content: "[前序上下文摘要: 学习者此前询问了动词词位与从句关联，已分析完毕]"`；
  - 彻底杜绝长对话导致的 Token 溢出与响应延迟劣化。

**Injected Instincts:**
- [ ] `[Instinct: Zero Data Loss]`: 首尾保留，中间折叠，永远保证最新问答对具备完整上下文。

**Subagent Prompt Scaffold:**
> "Implement Task 2: Turn-level message compaction in agent/internal/companion/compaction.go.
> Mode: AFK | Role: Go TDD Builder
> Goal: Introduce sliding window context compaction to keep multi-turn conversations within budget without token hard-truncation.
> Target Files: Create agent/internal/companion/compaction.go, Test agent/internal/companion/compaction_test.go, Modify agent/internal/companion/loop.go.
> TDD Steps:
> 1. Write failing test compaction_test.go with multi-turn messages exceeding maxChars (RED).
> 2. Implement CompactMessages with system anchor folding (GREEN).
> 3. Wire CompactMessages into RunLoop before CreateChatCompletionStream.
> 4. Verify exit 0 with go test -v ./internal/companion/...
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `agent/internal/companion/compaction_test.go` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement `CompactMessages` in `agent/internal/companion/compaction.go` (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Wire into `RunLoop` in `agent/internal/companion/loop.go`**
- [ ] **Step 6: Physical Evidence Gate**: `go test -v ./internal/companion/...` 退出码 0。
- [ ] **Step 7: Git atomic commit**

---

### Task 3: 云端主模型与本地 Ollama 级联热备 [Tier: 2-Standard] [Mode: AFK] [Role: Go TDD Builder]

**Files:**
- Modify: `agent/internal/companion/loop.go`
- Modify: `agent/cmd/delector/agent.go`
- Test: `agent/internal/companion/fallback_test.go`

**Interfaces:**
- Consumes: `primaryClient *openai.Client`, `fallbackClient *openai.Client`
- Produces: 
  - `CompanionAgent` 增设级联配置：`WithFallback(client *openai.Client, model string)`；
  - 当主通道（如 DeepSeek 公网）触发网络连接不可达（`ConnectError`）或 5xx 故障时，自动无损切换至本地模型（如 `qwen3.5:4b` @ `http://127.0.0.1:11434`）接续完成流式回答；
  - 保证离线/断网环境下伴学 Agent 依然高可用。

**Injected Instincts:**
- [ ] `[Instinct: Fallback Circuit]`: 仅在主模型物理连接失败或严重超时时切换，业务参数错误不误触发降级。

**Subagent Prompt Scaffold:**
> "Implement Task 3: Primary-to-local fallback cascade in agent/internal/companion/loop.go.
> Mode: AFK | Role: Go TDD Builder
> Goal: Enable transparent fallback from primary cloud client to local Ollama client when network is unreachable.
> Target Files: Modify agent/internal/companion/loop.go, Test agent/internal/companion/fallback_test.go, Modify agent/cmd/delector/agent.go.
> TDD Steps:
> 1. Write failing test TestCompanionLoopFallbackToLocal in fallback_test.go (RED).
> 2. Implement cascading stream failover in loop.go (GREEN).
> 3. Add --fallback-url and --fallback-model flags to delector agent in agent.go.
> 4. Verify exit 0 with go test -v ./internal/companion/...
> Return: Summary with Physical Execution Receipt."

**Step Breakdown:**
- [ ] **Step 1: Write failing test in `agent/internal/companion/fallback_test.go` (RED)**
- [ ] **Step 2: Run test and verify failure**
- [ ] **Step 3: Implement fallback cascade in `agent/internal/companion/loop.go` (GREEN)**
- [ ] **Step 4: Update CLI flags in `agent/cmd/delector/agent.go`**
- [ ] **Step 5: Physical Evidence Gate**: `go test -v ./internal/companion/...` 退出码 0。
- [ ] **Step 6: Git atomic commit**

---

### Task 4: 双语全景门禁与综合回归验证 [Tier: 1-Light] [Mode: AFK] [Role: Gatekeeper]

**Files:**
- Verify: Go 与 Python 全量回归

**Step Breakdown:**
- [ ] **Step 1: `cd agent && go test ./...` 100% PASS**
- [ ] **Step 2: `pytest tests/test_companion_*.py tests/test_llm_client.py` 100% PASS**
- [ ] **Step 3: 四道机械门禁验证 (`check_frontend_layers.py` 等) 100% PASS**
- [ ] **Step 4: `mypy --strict` & `ruff check` 100% PASS**
- [ ] **Step 5: 追加 `WORKMEMORY/work.log` 记录深化成果**

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
|---|---|---|---|
| 本地推测解码 (Speculative Decoding) | 需要本地 GPU 支持双模型并行 Token 验证 | 当本地接入专用 C++ 推理后端（如 llama.cpp）时 | Agent Team |
| 跨文章长程向量记忆 (RAG) | 当前侧重于单篇文章视口与会话级伴学 | 当遇见区引入跨文章知识库联想时 | Search Team |

---

## [NOTE] Out of Scope
- 修改德语依存语法解析内核算法（`spacy` / `stanza` 本地规则）。
- 变更前端纸质德式墨线视觉规范（保持原生 DOM 与零 `innerHTML` 铁律）。
