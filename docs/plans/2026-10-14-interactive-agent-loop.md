# DeLector 交互层「验证驱动 agent 循环」实施计划

> **Goal**: 按 ADR-0023（vault `08-Projects/DeLector/01-ADR/0023-…md`，`accepted`，**§8 为定稿口径**）把 `ai-polish` 从 one-shot「取神谕」改为**模型驱动流转 + 确定性裁判终审**的有界循环；并**先偿还该 ADR 自认的两处前置欠账**（Go 门禁两红灯 → LLM client 收口）。
> **Tech Stack**: Python 3.11 / FastAPI / httpx / Go（仅触及批处理侧测试）/ pytest
> **Spec Reference**: `08-Projects/DeLector/01-ADR/0023-interactive-layer-verification-driven-agent-loop.md`（§4.2 形态 · §4.4 前置 · §8 定稿记录）
> **Global Constraints**:
> - 零新依赖、**不引入任何 agent 框架**（ADR-0001 §1）；交互层留 Python（ADR-0010 §5 红线）
> - **测试一律 stub，MUST NOT 依赖真实 `DEEPSEEK_API_KEY`**（否则门禁恒 skip —— ADR §5 合规护栏）
> - 「第 2 轮违规数严格少于第 1 轮」**既是测试断言也是运行时策略**（`v_n ≥ v_{n-1} ⇒ break`）
> - **零静默失败**：未收敛 MUST 带原因码返回，且前端 MUST 可见（toast）
> - `deadline_s` MUST 严格小于外层请求超时（**到点次序**：内层先到点才能留下人话错误）
> - 工具面 = **任务级白名单参数**，不是全局 `TOOL_REGISTRY`；鉴权闸（谁是调用者）≠ 能力白名单（模型能调什么）
> - 行尾 CRLF；提交信息用中文 + 具体行号锚点
> **Branch**: `feat/interactive-agent-loop`（从 `master` 开；本计划的**实现类**任务全部在该分支上做、经 PR 落地。`[Tier: 1-Light]` 的纯文档/簿记项按 `docs/agents/ops.md` 第 12 条例外可直推）

---

## 🏛️ Decisions So Far

| # | 决策 | 依据 |
| --- | --- | --- |
| D1 | **流转由模型驱动**（模型自选工具；代码只做二值判断：有工具调用则继续、无则请求收尾） | ADR-0023 §8.1 **Q1-B** |
| D2 | 轮次上界 3 + 循环级 `{max_tokens_total, deadline_s}` | §8.1 **Q2-A** |
| D3 | **收尾必须过裁判**（无裁决不许终止 ⇒ 强制补一次裁判） | §8.1 **Q3-A** |
| D4 | 工具面 = 任务级最小白名单（只读且相关；`ingest`/`export`/`tts` 不暴露） | §8.1 **Q4-A** |
| D5 | 工具同进程直调；权限闸作**前置钩子** | §8.2 第 5 条 |
| D6 | 人类裁决环 MUST（`writer.js` 逐 hunk 采纳/保留；「保留原句」作裁判集不足的回归信号） | §8.2 第 3 条 |
| D7 | 施行顺序 **① Go 两红灯 → ② client 收口 → ③ 循环 + 白名单 + UI** | §4.4 / §8.5 |

### Phase 1 物理证据（2026-10-14 实测，非引述）

| 锚点 | 实测 | 用途 |
| --- | --- | --- |
| `delector/routes/main.py` 裸 HTTP | **5 处**：`413/516/1449/1544/2374`（`/chat/completions` 在 `415/518/1451/1546/2376`），超时各写各的 **30/15/20/10/30** | Task 3 收口对象 |
| `delector/services/writing.py:607` | `def analyze_a1_email(text: str, leitpunkte: Optional[List[str]] = None) -> Dict[str, Any]` | Task 4/6 的裁判 |
| `delector/tools/writing_check.py:14` | `async def run(payload)` → `analyze_a1_email(text, leitpunkte)` | 白名单候选（只读） |
| `delector/tools/analyze.py:9` | `async def run(payload)` → `process_german_text(text)` | 白名单候选（只读形态） |
| `delector/tools/vocab_stats.py:68` | `async def run(payload)`（纯函数统计） | 白名单候选（只读） |
| `delector/tools/ingest.py:13` | → `fetch_remote_html(url)` | **排除**（出网） |
| `delector/tools/export.py:14` | 写 `output_path` | **排除**（写盘） |
| `delector/tools/tts.py:10` | 生成音频 | **排除**（副作用/CPU） |
| `agent/integration_encounter_test.go:107` | `if len(rows) != 2 { t.Fatalf("…应命中 2 行，实得 %d") }` | Task 1 红灯① |
| `agent/integration_test.go:57` | `mustNotSkipEnv` → `exec.LookPath("python")` | Task 2 红灯② |
| `.github/workflows/*.yml` grep `integration` | **零命中** | Task 2 接入 CI 的欠账 |
| 既有测试面 | `tests/test_goethe_a1_writing.py` · `tests/test_writing_rules.py` · `tests/test_ai_endpoints_localhost_gate.py` | 新测试文件放 `tests/test_ai_polish_loop.py` |

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: Go 门禁红灯①——断言被预置短文污染 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `agent/integration_encounter_test.go`
- Test: `agent/integration_encounter_test.go`（Go 无独立测试文件，断言即测试）

**Interfaces:**
- Consumes: `encounterTexts(t, ctx) []TextRow`（既有 helper）
- Produces: 门禁 5 改为**相对断言**（`import-pack 前快照 + 2 == 后快照`），不再假设空库

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修 `agent/integration_encounter_test.go` 门禁 5：现断言 `len(rows) != 2` 假设空库，但 `create_app()` 启动时会注入 7 篇预置短文 ⇒ 真实值 9。改为「import-pack **前**先把 `/api/encounter/texts` 的行数与标题集合存为快照，import **后**断言『新增恰好 2 行且标题匹配、level 归一 A1』」。RUN：`cd agent && go test -tags integration -run TestEncounterRealChain ./... -v`，带回原始输出（该门禁在本机可能因红灯②而 skip —— 若 skip，MUST 如实报告 skip 及其原因行，不许声称通过）。"

**Step Breakdown:**
- [ ] Step 1: 先跑一次取**真实失败输出**（RED 证据：实得 9 行）
- [ ] Step 2: 改为前后快照相对断言（GREEN）
- [ ] Step 3: 跑门禁并把原始输出（含 skip 情形）写进回执
- [ ] Step 4: `git diff` + 原子提交

---

### Task 2: Go 门禁红灯②——解释器探测 + 接入 CI [Tier: 2-Standard] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Modify: `agent/integration_test.go`（`mustNotSkipEnv` 的 python 探测）
- Modify: `.github/workflows/ci.yml`（新增一个 integration job）
- Test: 无（以 CI 运行结果为准）

**Interfaces:**
- Consumes: `exec.LookPath` / `preflightTO`
- Produces: 探测改为**候选列表**（`$DELECTOR_PYTHON` → `python3` → `python`），且**逐个验证 uvicorn+fastapi 可导入**才认；CI 新增 job 带 `-tags integration`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "① 把 `agent/integration_test.go` 的 `mustNotSkipEnv` 从硬编码 `LookPath(\"python\")` 改为按序探测候选解释器（`$DELECTOR_PYTHON` → `python3` → `python`），对每个候选**实测 `-c 'import uvicorn, fastapi'`**，第一个通过的即为解释器，全不通过才 `Skipf`；② 在 `.github/workflows/ci.yml` 新增 integration job（ubuntu，装 `requirements.txt`，跑 `cd agent && go test -tags integration ./...`），**加 `timeout-minutes`**（沿用本仓五档口径后的保守值）。RUN：本机 `DELECTOR_PYTHON=python3 go test -tags integration -run TestEncounterRealChain ./... -v` 必须**真跑**（不是 skip），带回原始输出。**不得**为了让门禁变绿而放宽断言。"

**Step Breakdown:**
- [ ] Step 1: 本机复现 skip（RED 证据：skip 原因行）
- [ ] Step 2: 实现候选探测（GREEN：真跑）
- [ ] Step 3: CI job 写入（含 timeout-minutes）
- [ ] Step 4: 提交（CI 定义属**非文档类** ⇒ 走本计划分支 + PR）

---

### Task 3: LLM client 收口（5 处裸 HTTP → 单一 client） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/services/llm_client.py`
- Modify: `delector/routes/main.py`（`413/516/1449/1544/2374` 五处收敛）
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `base_url` / `DEEPSEEK_API_KEY`（既有取值方式，不改配置面）· `httpx.AsyncClient`
- Produces: `async def chat(messages: list[dict], *, max_tokens: int, timeout: float, model: str) -> dict`（**唯一出网口**；payload MUST 含 `max_tokens`）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "新建 `delector/services/llm_client.py` 收敛 5 处重复的 `httpx.AsyncClient + chat/completions + Authorization + json.loads`。要求：① payload **MUST** 带 `max_tokens`（当前全仓生成路径零处设置，`main.py:2378-2385`）；② 超时由调用方传入（保留各处现值 30/15/20/10/30，语义不变）；③ 错误语义与现状一致（失败仍 502，别顺手改）；④ TDD：先在 `tests/test_llm_client.py` 写失败测试（**mock transport，不发真请求**），覆盖『max_tokens 必现』『超时透传』『HTTP 错误映射』。RUN：`python -m pytest tests/test_llm_client.py -q` 与 `python -m pytest tests/test_goethe_a1_writing.py tests/test_writing_rules.py tests/test_ai_endpoints_localhost_gate.py -q`（**只许新增，不许放宽既有断言**）。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：`max_tokens` 不在 payload）
- [ ] Step 2: 跑并确认预期失败
- [ ] Step 3: 实现 client + 收敛 5 处（GREEN）
- [ ] Step 4: 关联套件全绿 + `ruff` + mypy 四档
- [ ] Step 5: 原子提交

---

### Task 4: 循环内核（有界 + 预算 + 停止策略 + 裁判终审） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/services/polish_loop.py`
- Test: `tests/test_ai_polish_loop.py`

**Interfaces:**
- Consumes: `llm_client.chat(...)` · `writing_check.run(payload)`（经白名单）· `analyze_a1_email`
- Produces: `async def run_polish_loop(*, text: str, leitpunkte: list[str] | None, tools: Mapping[str, Callable], budget: Budget) -> LoopResult`，其中 `Budget = (max_turns:int=3, max_tokens_total:int, deadline_s:float)`，`LoopResult = (text:str, converged:bool, reason:str|None, rounds:int, violations:list)`，`reason ∈ {ok, no_improvement, turn_limit, token_budget, deadline, judge_unreliable, judge_error}`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "按 ADR-0023 §4.2/§8.2 实现循环内核（`delector/services/polish_loop.py`），**全部依赖注入、全部 stub 测试**（严禁真实 API Key）。必须逐条实现：① 二值判断——模型输出含工具调用则执行并继续，无则**收尾请求**；② **收尾终审守卫**：无裁判裁决的收尾 MUST 被驳回并强制补一次裁判；③ 运行时策略 `v_n >= v_{n-1} ⇒ break` 并回退 `argmin(violations)` 候选，`reason='no_improvement'`；④ 哨兵 `v_n == v_{n-1} and n>=2 ⇒ reason='judge_unreliable'`；⑤ 每轮**前置**检查 `max_tokens_total` 与 `deadline_s`，超支即 break 并给原因码；⑥ 裁判异常按 errors-as-messages 单轮降级（记 `judge_error`，**不得** 500）；⑦ 证据注入前按行数+字节双限截断。测试用例 MUST 至少覆盖：不降即停、超轮次、超 token、超 deadline、裁判抛异常、无裁决不许收尾（**删掉守卫必须变红**）。RUN：`python -m pytest tests/test_ai_polish_loop.py -q`。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED，含「删守卫必红」的判别力用例）
- [ ] Step 2: 跑并记录预期失败原文
- [ ] Step 3: 实现内核（GREEN）
- [ ] Step 4: 逐条变异自证（抽掉守卫 / 抽掉预算 / 抽掉哨兵 ⇒ 必须红）
- [ ] Step 5: 原子提交

---

### Task 5: 工具白名单 + 前置钩子（同进程直调） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/services/polish_tools.py`
- Test: `tests/test_ai_polish_loop.py`（同一文件追加，或 `tests/test_polish_tools.py`）

**Interfaces:**
- Consumes: `delector.tools.{writing_check, analyze, vocab_stats}.run`
- Produces: `POLISH_TOOL_ALLOWLIST: Mapping[str, Callable]`（**恰好 3 项，只读**）· `async def call_tool(name: str, payload: dict, *, hooks: Sequence[Hook]) -> dict`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "建 `delector/services/polish_tools.py`：① 白名单**恰好** `writing_check` / `analyze` / `vocab_stats`（同进程直调 `.run`，**不经 HTTP**）；② `ingest` / `export` / `tts` 出现在白名单里 MUST 立即失败（写一条**断言白名单与 `TOOL_REGISTRY` 差集**的测试：差集 MUST 含这三个名字）；③ 前置钩子链（权限/审计）在调用前串行执行，钩子抛异常 ⇒ 该次调用被拒并作为消息返回（不炸循环）。RUN：`python -m pytest tests/test_polish_tools.py tests/test_ai_polish_loop.py -q` 与 `python -m pytest tests/test_ai_endpoints_localhost_gate.py -q`。"

**Step Breakdown:**
- [ ] Step 1: 写失败测试（RED：白名单缺失/含写工具）
- [ ] Step 2: 跑并确认失败
- [ ] Step 3: 实现白名单 + 钩子（GREEN）
- [ ] Step 4: 变异自证（把 `ingest` 加进白名单 ⇒ 必须红）
- [ ] Step 5: 原子提交

---

### Task 6: 返回契约 + 前端进度/取消 + 契约闸同步 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/routes/main.py`（`ai-polish` 端点返回体）
- Modify: `static/js/writer.js`（进度「第 N/3 轮」+ 取消按钮 + 未收敛 toast；沿用既有逐 hunk 裁决 UI）
- Test: `tests/test_goethe_a1_writing.py`（追加契约断言）+ `python tools/check_frontend_api_contract.py`

**Interfaces:**
- Consumes: `run_polish_loop(...) -> LoopResult`
- Produces: 响应体新增 `converged: bool` 与 `unconverged_reason: str | None`（**既有字段一律不动**）；前端 MUST 在 `converged == false` 时 toast 原因

**Subagent Prompt Scaffold (for /dfs-exec):**
> "给 `ai-polish` 端点加 `converged` / `unconverged_reason` 两字段（**只增不改**，`main.py:2420-2427` 既有结构保持），并在 `static/js/writer.js` 实现：逐轮进度文案（第 N/3 轮）、取消（`AbortController` 或等价机制）、`converged=false` 时 toast 原因。契约同步 MUST 跑 `python tools/check_frontend_api_contract.py`（前端契约闸，仓内既有）。注意 `01-Rules/ENDPOINT-CONTRACT-FRONTEND-SYNC`：契约改动与前端改动 MUST 同批。RUN：`python -m pytest tests/test_goethe_a1_writing.py tests/test_writer_mobile.py -q` + 契约闸 + `ruff`。"

**Step Breakdown:**
- [ ] Step 1: 写契约失败测试（RED：`converged` 不在响应）
- [ ] Step 2: 跑并确认失败
- [ ] Step 3: 端点 + 前端实现（GREEN）
- [ ] Step 4: 契约闸 + 发版守护套件
- [ ] Step 5: 原子提交

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A] 裁判集扩充（ADR §4.3 的"成败所在"）**：A1 真实评分维度中**哪些可纯规则化、哪些必须 LLM 辅助**未测（ADR §6 Unknown 1）⇒ **不切分**。它天然是**下一个子计划**（`/dfs-plan` 续作），不得在本计划里投机拆任务。
- **[Unknown B] 循环真实轮次分布与 token 上界**：需先有 stub 基线或真 Key 实测（ADR §6 Unknown 2）⇒ `max_tokens_total` 的**默认值待 Task 4 的 stub 基线给出**，本计划只规定"必须有该参数"。
- **[Unknown C] 是否需要 function calling 的原生形态**：D1 只要求"模型能选工具"，**披露协议**（原生 tool_calls vs JSON 契约字段）未定 ⇒ Task 4 实现时以"最小改动 + 可 stub"为准，选定后回写 ADR §6。
- **[Unknown D] `lookup_core_vocab`（`writing.py:680`）是否会抛**（ADR §8.4 标 UNVERIFIED）⇒ Task 4 的 `judge_error` 用例先按"会抛"设计，实测后收窄。

## 🚫 Out of Scope

- 不引入 agent 框架（ADR-0001 §1）；不改主体语言、不动 Go 批处理功能边界（ADR-0021 / ADR-0010 §5）
- 不做通用对话 agent、不做多工具编排（ADR §4.5）
- 不为"AI 润色"以外的功能接循环（首个落点仅 `ai-polish`）
- 不在本计划内扩裁判集（见 Fog of War Unknown A）
