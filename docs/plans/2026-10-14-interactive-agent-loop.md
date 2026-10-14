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

## ⚠️ 执行期发现与顺序调整（2026-10-14，Task 1 开工前）

实跑真链路门禁发现**第三个红灯**，它推翻了 Task 1 的可验证前提：

- **门禁在本机真的跑了**（红灯②**未复现**）：本 shell 的 `python` 就是带依赖的 3.11 ⇒ `exec.LookPath("python")` 与依赖探测均通过。⇒ 红灯②是 **shell/PATH 相关**而非机器相关，CI 上的表现需另测。
- **它在更早的一步就红了**：`agent/integration_encounter_test.go:95` —— 两个 pack 均 `import-pack 返回 500`（**不是 Python 侧的 bug**）。
- **真根因**：`127.0.0.1:8001` 被一个 **3 小时前的孤儿进程**占用（`uvicorn delector.server:app`，PID 6808，父进程已死）；而门禁把 `baseURL` **硬编码**为 `127.0.0.1:8001`（`agent/integration_test.go:37`）且**不校验服务身份** ⇒ 起服 bind 失败后**仍向 8001 发业务请求**，被外来进程应答。
- **真实风险不是假红，是假绿**：外来服务若恰好答得对，门禁会**替别人的服务背书**。孤儿进程已清理，**但根因仍在** ⇒ 新增 Task 0 治本。

**执行顺序据此调整为**：`Task 0（身份与失败语义）→ Task 2 的代码半（解释器候选探测）→ Task 1（断言相对化）→ Task 2 的 CI 半（HITL）→ Task 3 → Task 4 → Task 5 → Task 6`。

> 与 ADR-0023 §4.2 同族：产品侧要求"端口被占时不留指向别人的地址文件"，**门禁侧同样要"端口被占时不测别人的服务"**。测试基础设施也会静默失败，而它的静默失败直接污染证据链。

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

### Task 0: 集成门禁的「身份与失败语义」（**执行期新增**） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `agent/integration_test.go`（`baseURL` 用法 / 起服后的身份探针 / 失败语义）
- Modify: `agent/integration_encounter_test.go`（同一 helper 的调用点）
- Test: 门禁自身（`go test -tags integration`）

**Interfaces:**
- Consumes: `GET /api/health`（`delector/routes/main.py:2690`，契约：**接受 503、只看 `app`/`version` 两个身份字段**，与 Python 侧 `server_lifecycle.probe_identity` 同义）
- Produces: `func assertHostedServiceIdentity(t *testing.T, baseURL string)` —— 身份不符/不可达即**fail-fast 并给出可操作诊断**；以及"起服失败则不再发业务请求"的失败语义

**Subagent Prompt Scaffold (for /dfs-exec):**
> "修 `agent/` 集成门禁的两处**静默失败**：① 起服（bind 8001）失败后**仍继续向 8001 发业务请求** ⇒ 会打到外来进程（实测：3 小时前的孤儿 uvicorn 回了 500，断言在 `integration_encounter_test.go:95` 假红）。改为：起服失败 ⇒ **立刻 fail-fast（或按既有约定真 skip）**，绝不继续；② 起服成功后 MUST 探 `GET /api/health` 断言 `app=="delector"` 且 `version` 与期望一致（**503 也算通过身份**，只读身份字段——与 `server_lifecycle.probe_identity` 契约对齐），身份不符即 fail-fast 并打印『8001 上是一个外来服务（app/version=X）』。**身份校验不等于实例校验**：同版本同 app 的另一个实例仍会通过 ⇒ 因此**首选同时改为动态空闲端口**（`net.Listen("tcp","127.0.0.1:0")` 取端口后传给 uvicorn，并同步 `baseURL` 由 const 变变量；8001 退化为可覆盖默认值，注释里的『端口约定』同步改写）。RUN：先**故意占用 8001**（如本机留一个 uvicorn）跑一次证明 fail-fast 生效，再释放后跑一次证明真链路通过；两条原始输出都要带回。"

**Step Breakdown:**
- [ ] Step 1: 复现静默失败（占用 8001 后跑门禁，证明它仍发业务请求并假红/假绿）——RED 证据
- [ ] Step 2: 实现身份探针 + 失败语义（GREEN）
- [ ] Step 3: 动态端口（推荐项）替代硬编码 8001，同步注释与调用点
- [ ] Step 4: 两条对照运行（占端口 ⇒ fail-fast；空端口 ⇒ 通过）
- [ ] Step 5: 原子提交

---

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
- **Produces 的两处执行期补充（2026-10-15 定案，编排者批准）**：
  1. **依赖注入参数**：除 `text/leitpunkte/tools/budget` 四个必填项外，另有 `chat / judge / violations_of / dispatch / clock` 五个**仅测试用**的注入点（默认回落真身）。这不是范围扩张 —— 本任务 scaffold 第一句就是「**全部依赖注入、全部 stub 测试**（严禁真实 API Key）」，没有注入点就只能靠真 Key 或 monkeypatch 全局，两者都违反仓规。
  2. **`reason` 增加 `cancelled`**：Task 6 的取消按钮需要内核有「用户中止」的出口，否则取消只能表现为连接中断（前端拿不到人话原因）。故**在 Task 4 就地留位**，避免 Task 6 回头改内核 —— 这是有计划的范围调整，不是顺手加的。
- **已知边界（CRV 黄卡，刻意不改）**：基线 `v_0 == 0`（原文已零 error）时**不早退** —— 润色还有用词/地道化价值，裁判只管 error 级。副作用：若首个候选反而变差，会回退到零违规的原文并报 `converged=false / no_improvement`。文案上由 Task 6 的前端兜住（文本本身是干净的）。

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
- ~~**[Unknown B] 循环真实轮次分布与 token 上界**~~ **（2026-10-15 部分收敛，见 Task 4 交付）**：
  - **token 上界已定案**：`DEFAULT_MAX_TOKENS` **保留 4096**（实测单轮最坏 691 token，2× 余量充足）；`DEFAULT_MAX_TOKENS_TOTAL = 4096`（刻意 < `4096 × 3`，使循环级预算**真会咬合**，不是真空闸）；`DEFAULT_DEADLINE_S = 18.0`（严格小于前端 `DEFAULT_TIMEOUT_MS=25000`，内层先到点）。
  - **仍待回测**：① 折算系数 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 是 **UNVERIFIED 假设**（本机 `tiktoken` / `transformers` 实测均 `ModuleNotFoundError`，拿不到真 BPE 计数）；② **真实轮次分布** —— stub 基线只能给出"收敛于第 N 轮的**条件**"，真实分布须有 Key 后回测。
- **[Unknown C] 是否需要 function calling 的原生形态**：**已定案（2026-10-15）= JSON 契约字段**（回复里的 `tool_call` 键），不用原生 `tool_calls`。理由三条（可 stub / 与 `llm_client.chat` 的 dict 返回值同形且不动 Task 3 刚收口的 client / 零新依赖），已写进 `polish_loop.py` 模块 docstring。**待办**：按原计划把它**回写 ADR-0023 §6**（本计划不代劳 ADR）。
- **[Unknown D] `lookup_core_vocab`（`writing.py:680`）是否会抛**（ADR §8.4 标 UNVERIFIED）⇒ Task 4 的 `judge_error` 用例先按"会抛"设计，实测后收窄。

## 🚫 Out of Scope

- 不引入 agent 框架（ADR-0001 §1）；不改主体语言、不动 Go 批处理功能边界（ADR-0021 / ADR-0010 §5）
- 不做通用对话 agent、不做多工具编排（ADR §4.5）
- 不为"AI 润色"以外的功能接循环（首个落点仅 `ai-polish`）
- 不在本计划内扩裁判集（见 Fog of War Unknown A）
