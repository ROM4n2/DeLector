# C3 实施计划：真轮次分布与真 Token 计数回测 (Token Counting & Turn Distribution Backtest)

> **Goal**: 接入生产链路真实 Usage 透出，建立德语 A1 文本 Token 折算比率与真实轮次分布回测工具，验证 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 的保守性边界与循环预算上界，正式闭环 ADR-0023 §6 Unknown B 与 C3 台账。
> **Tech Stack**: Python 3.11 / FastAPI / pytest / JSON Lines
> **Spec Reference**:
> - `docs/adr/2026-10-14-interactive-layer-verification-driven-agent-loop.md`（ADR-0023 §6 Unknown B / §10.2）
> - `docs/adr/2026-10-16-adr-0024-gaming-control-experiment-verdict-metric.md`（ADR-0024 §6）
> - `docs/reviews/2026-10-16-open-items-backlog.md`（C3 项）
> - `docs/reviews/2026-10-16-judge-gaming-control-experiment.md`（N=20 实测全景报告）
> **Global Constraints**:
> - **零新依赖（ADR-0001 §1）**：严禁为了测 token 引入 `tiktoken`、`transformers` 等重量级分词库；基于真实 API 信封权威 `usage` 统计实测。
> - **零 Key 门禁与离线可达（ADR-0023 §5）**：所有单元测试与 CI 门禁严禁触碰真 Key 或外网出网；分析器必须支持从已有落盘记录（JSONL / JSON fixture）中执行离线确定性回测。
> - **零静默破坏既有契约**：`llm_client.chat` 的 `include_usage` 维持 opt-in；生产端点只在内部向 `run_polish_loop` 供应更精确的真实数值，不破坏前端既有 JSON/SSE 响应字段。
> - **文件契约**：全文件 UTF-8 CRLF，0 lone LF；`mypy --strict delector tools` 与 `mypy --follow-imports=skip tests` 零错误；`ruff check .` 零告警。
> **Branch**: `feature/c3-token-and-turn-distribution` — 从 `master` 切出，全套门禁全绿后提 PR 合入，严禁直推 `master`。

---

## 🏛️ Decisions So Far

- [ADR-0023 §10.2]: 确立 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 为 **UNVERIFIED 假设**，循环级预算常量 `DEFAULT_MAX_TOKENS = 4096`、`DEFAULT_MAX_TOKENS_TOTAL = 4096`、`DEFAULT_DEADLINE_S = 18.0` 基于 2000 字符最坏输入录制桩建立。
- [PR #143 (B5)]: `llm_client.chat` 引入 opt-in `include_usage=True` 透出信封真实 usage；`bench_judge_gaming.py` 的 `RealChat` 启用真 token 记账并扩展 `RunRecord` 为 15 键。
- [PR #147 (C1)]: 落地裁判结论回灌（Verifier-in-the-Loop），使循环具备根据 `[裁判反馈]` 开展二轮自修正的能力，重塑了真实运行下的轮次收敛动力学。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 生产端点 Usage 权威透出与精确计量接入 [Tier: 2-Standard] [Mode: AFK] [Role: Integrator]

**Files:**
- Modify: `delector/routes/main.py:2345-2375`
- Test: `tests/test_server.py:7100-7150`

**Interfaces:**
- Consumes: `llm_client.chat(..., include_usage=True) -> dict[str, Any]`
- Produces: `_PolishReplyRecorder.usage: dict[str, int] | None`, `reply["usage"]` transparently delivered to `run_polish_loop`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Non-Breaking Contract]`: `include_usage=True` 合并进返回字典，既有 `corrected_text`, `notes_zh`, `error_count` 解析原样保留。
- [ ] `[Instinct: Precision Preference]`: `polish_loop.completion_tokens_of` 优先读取 `usage.completion_tokens`，仅在缺失时 fallback 字符折算。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 生产端点 Usage 权威透出与精确计量接入.
> Mode: AFK | Role: Integrator
> Goal: Wire `include_usage=True` in `_PolishReplyRecorder.__call__` in `delector/routes/main.py`, so production calls to `run_polish_loop` receive real token usage from DeepSeek API response envelopes.
> Steps:
> 1. In `tests/test_server.py`, add `test_ai_polish_records_and_uses_real_usage_tokens` asserting:
>    - When `llm_client.chat` returns mock payload containing `\"usage\": {\"prompt_tokens\": 100, \"completion_tokens\": 50, \"total_tokens\": 150}`, the recorder captures it.
>    - In `run_polish_loop`, token budget consumes exactly 50 tokens (completion_tokens) rather than estimating from length.
>    Verify test failure before implementation (RED).
> 2. In `delector/routes/main.py`:
>    - In `_PolishReplyRecorder.__init__`: initialize `self.usage: dict[str, int] | None = None`.
>    - In `_PolishReplyRecorder.__call__`: pass `include_usage=True` to `llm_client.chat(...)`.
>    - In `_PolishReplyRecorder._capture`: capture `self.usage = reply.get(\"usage\")`.
> 3. Verify GREEN: run `python3 -m pytest tests/test_server.py -k \"test_ai_polish\" -v`, run `ruff check delector/routes/main.py tests/test_server.py`, run `mypy --strict delector/routes/main.py`.
> 4. Ensure CRLF clean and output raw execution receipts."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)** in `tests/test_server.py`.
- [ ] **Step 2: Run test and verify it fails with expected message**.
- [ ] **Step 3: Implement minimal production code (GREEN)** in `delector/routes/main.py`.
- [ ] **Step 4: Run tests and verify all green**.
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**.
- [ ] **Step 6: Physical Evidence Gate**: Capture raw terminal execution receipt (Command + Exit code: 0 + test pass count + git diff).
- [ ] **Step 7: Git atomic commit** on `feature/c3-token-and-turn-distribution`.

---

### Task 2: Token 折算比率与字符/Token 模型回测分析器 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_token_distribution.py`
- Create: `tests/test_bench_token_distribution.py`
- Create: `tests/fixtures/token_backtest_sample.json`

**Interfaces:**
- Consumes: `records: Sequence[dict[str, Any]]`
- Produces: `def analyze_token_ratios(records: Sequence[dict[str, Any]]) -> TokenRatioReport`
- Data Model:
  ```python
  @dataclass(frozen=True)
  class TokenRatioReport:
      sample_count: int
      prompt_chars_total: int
      prompt_tokens_total: int
      prompt_chars_per_token_mean: float
      completion_chars_total: int
      completion_tokens_total: int
      completion_chars_per_token_mean: float
      completion_chars_per_token_p50: float
      completion_chars_per_token_p95: float
      conservative_bound_coverage: float  # estimate >= real 的覆盖率（目标 100%）
      recommended_estimate_factor: float
  ```

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Defensive Math]`: 零除防护（`tokens == 0` 时跳过或赋予下限）；浮点精度格式化保留 3 位。
- [ ] `[Instinct: Determinism]`: 纯函数计算，不依赖时间或全局随机数；单测完全依靠静态 fixture 保证 0 Key。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: Token 折算比率与字符/Token 模型回测分析器.
> Mode: AFK | Role: TDD Builder
> Goal: Build pure statistical analysis for characters-per-token ratio from execution records, verifying whether CHARS_PER_TOKEN_ESTIMATE = 3.0 holds as a conservative safe upper bound.
> Steps:
> 1. Create `tests/fixtures/token_backtest_sample.json` with 10 synthetic yet realistic German A1 execution records containing `prompt_tokens`, `completion_tokens`, and text bodies.
> 2. In `tests/test_bench_token_distribution.py`, write tests for `analyze_token_ratios`:
>    - Computes mean, p50, p95 chars-per-token for completion and prompt.
>    - Verifies conservative bound coverage against `estimate_tokens(s) = ceil(len(s)/3.0)`.
>    - Handles zero tokens or empty records gracefully without DivisionByZero.
>    Verify RED.
> 3. In `tools/bench_token_distribution.py`, implement `analyze_token_ratios` adhering strictly to data models and typing.
> 4. Run `python3 -m pytest tests/test_bench_token_distribution.py -v`, `ruff check tools/bench_token_distribution.py tests/test_bench_token_distribution.py`, `mypy --strict tools/bench_token_distribution.py`.
> 5. Output raw execution receipts."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)** in `tests/test_bench_token_distribution.py` + fixture.
- [ ] **Step 2: Run test and verify it fails with expected message**.
- [ ] **Step 3: Implement minimal production code (GREEN)** in `tools/bench_token_distribution.py`.
- [ ] **Step 4: Run tests and verify all green**.
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**.
- [ ] **Step 6: Physical Evidence Gate**: Capture raw terminal execution receipt.
- [ ] **Step 7: Git atomic commit** on `feature/c3-token-and-turn-distribution`.

---

### Task 3: 真实轮次分布与终止策略回测统计器 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/bench_token_distribution.py`
- Modify: `tests/test_bench_token_distribution.py`

**Interfaces:**
- Consumes: `records: Sequence[dict[str, Any]]`
- Produces: `def analyze_turn_distribution(records: Sequence[dict[str, Any]]) -> TurnDistributionReport`
- Data Model:
  ```python
  @dataclass(frozen=True)
  class TurnDistributionReport:
      total_runs: int
      round_counts: dict[int, int]          # {1: n1, 2: n2, 3: n3, ...}
      round_percentages: dict[int, float]   # {1: p1, 2: p2, 3: p3, ...}
      mean_rounds: float
      median_rounds: float
      converged_count: int
      converged_rate: float
      reasons: dict[str, int]               # {"ok": ..., "no_improvement": ..., "judge_unreliable": ...}
      tokens_per_round_mean: float
      elapsed_per_round_mean: float
  ```

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Multidimensional Grouping]`: 支持按文体（`letter` vs `prose`）或评测臂（`A1`, `A2`, `A3`）分群汇总。
- [ ] `[Instinct: Zero-Loss Integrity]`: 保证 `sum(round_counts.values()) == total_runs`，不可漏记异常退出用例。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 真实轮次分布与终止策略回测统计器.
> Mode: AFK | Role: TDD Builder
> Goal: Implement turn distribution and convergence metrics analysis in `tools/bench_token_distribution.py`.
> Steps:
> 1. In `tests/test_bench_token_distribution.py`, add tests for `analyze_turn_distribution`:
>    - Test round frequency histogram ({1: count, 2: count, 3: count}) and percentages.
>    - Test convergence rate and reason distribution breakdown.
>    - Test genre-stratified aggregation (letter vs prose).
>    Verify RED.
> 2. In `tools/bench_token_distribution.py`, implement `analyze_turn_distribution`.
> 3. Run `python3 -m pytest tests/test_bench_token_distribution.py -v`.
> 4. Ensure `ruff check` and `mypy --strict` pass cleanly.
> 5. Output raw execution receipts."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)** in `tests/test_bench_token_distribution.py`.
- [ ] **Step 2: Run test and verify it fails with expected message**.
- [ ] **Step 3: Implement minimal production code (GREEN)** in `tools/bench_token_distribution.py`.
- [ ] **Step 4: Run tests and verify all green**.
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**.
- [ ] **Step 6: Physical Evidence Gate**: Capture raw terminal execution receipt.
- [ ] **Step 7: Git atomic commit** on `feature/c3-token-and-turn-distribution`.

---

### Task 4: CLI 报告生成器与确定性数据导入接口 [Tier: 1-Light] [Mode: AFK] [Role: Tooling Engineer]

**Files:**
- Modify: `tools/bench_token_distribution.py`
- Modify: `tests/test_bench_token_distribution.py`

**Interfaces:**
- Consumes: CLI options: `--from-records PATH` (JSON or JSONL), `--json`, `--output PATH`
- Produces: `def main(argv: Sequence[str] | None = None) -> int` (Exit 0=success, 1=corrupt data, 2=file missing)

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Format Diversity]`: 支持读取 `.json` 与 `.jsonl` 双格式数据流。
- [ ] `[Instinct: Non-Crashing IO]`: 文件不存在或 JSON 格式破坏时给出人话 stderr 并退出 1 或 2，绝不产生无格式 traceback。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: CLI 报告生成器与确定性数据导入接口.
> Mode: AFK | Role: Tooling Engineer
> Goal: Complete CLI interface for `tools/bench_token_distribution.py` supporting terminal report rendering and JSON export.
> Steps:
> 1. In `tests/test_bench_token_distribution.py`, add CLI tests:
>    - `--from-records <fixture.json>` prints formatted summary to stdout and exits 0.
>    - `--from-records <fixture.json> --json` prints valid JSON.
>    - Missing file exits 2.
>    - Corrupt JSON exits 1.
> 2. In `tools/bench_token_distribution.py`, wire `argparse` and `main()`.
> 3. Verify GREEN: full test suite passes.
> 4. Output raw execution receipts."

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)** in `tests/test_bench_token_distribution.py`.
- [ ] **Step 2: Run test and verify it fails with expected message**.
- [ ] **Step 3: Implement minimal CLI code (GREEN)** in `tools/bench_token_distribution.py`.
- [ ] **Step 4: Run tests and verify all green**.
- [ ] **Step 5: Physical Evidence Gate**: Capture CLI command execution receipts.
- [ ] **Step 6: Git atomic commit** on `feature/c3-token-and-turn-distribution`.

---

### Task 5: 真实采样回测与 ADR-0023 §6 Unknown B 闭环报告 [Tier: 3-Critical] [Mode: HITL] [Role: Benchmarker]

**Files:**
- Create: `docs/reviews/2026-10-17-c3-token-and-turn-backtest-report.md`
- Modify: `delector/services/polish_loop.py:90-105`
- Modify: `docs/reviews/2026-10-16-open-items-backlog.md`
- Test: `tests/test_ai_polish_loop.py`

**Interfaces:**
- Consumes: 回测统计产物（来自 Task 4 的 CLI 运行输出与真实/离线样本比对）
- Produces: 官方实测报告、代码注释从 `UNVERIFIED 假设` 更新为 `VERIFIED 实测标定`、闭环 backlog C3

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Academic Rigor]`: 统计数据标明样本量 $N$、置信区间或分位数，不使用模糊修饰词。
- [ ] `[Instinct: Conservative Safety Margin]`: 明确记录推荐常数与安全边界，若 $3.0$ 保守有效则予以物理论证锁定。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 真实采样回测与 ADR-0023 §6 Unknown B 闭环报告.
> Mode: HITL | Role: Benchmarker
> Goal: Run token and turn distribution analysis on benchmark records, generate official report, update polish_loop docstrings, and close C3 backlog.
> Steps:
> 1. Execute `python3 tools/bench_token_distribution.py --from-records docs/reviews/2026-10-16-judge-gaming-control-experiment.raw.json` (or fresh real run if HITL provides Key).
> 2. Create `docs/reviews/2026-10-17-c3-token-and-turn-backtest-report.md` detailing:
>    - Real chars-per-token distribution (median, p95).
>    - Evaluation of `CHARS_PER_TOKEN_ESTIMATE = 3.0` conservatism.
>    - Real turn distribution across genres and convergence rates.
>    - Verification of `DEFAULT_MAX_TOKENS = 4096` headroom.
> 3. In `delector/services/polish_loop.py`, update `CHARS_PER_TOKEN_ESTIMATE` docstrings from UNVERIFIED to VERIFIED with exact citation to the report.
> 4. In `docs/reviews/2026-10-16-open-items-backlog.md`, mark C3 as completed.
> 5. Output raw execution receipts."

**Step Breakdown:**
- [ ] **Step 1: Execute backtest tool on record sets**.
- [ ] **Step 2: Generate official review report** in `docs/reviews/2026-10-17-c3-token-and-turn-backtest-report.md`.
- [ ] **Step 3: Update `CHARS_PER_TOKEN_ESTIMATE` docstring** in `polish_loop.py`.
- [ ] **Step 4: Update backlog table** in `docs/reviews/2026-10-16-open-items-backlog.md`.
- [ ] **Step 5: Physical Evidence Gate**: Capture test suite pass and report output.
- [ ] **Step 6: Git atomic commit** on `feature/c3-token-and-turn-distribution`.

---

### Task 6: 门禁全景复核与交付 PR [Tier: 1-Light] [Mode: AFK] [Role: Cleaner]

**Files:**
- Modify: `WORKMEMORY/work.log`
- Modify: `docs/plans/2026-10-17-c3-token-and-turn-distribution-backtest.md`

**Step Breakdown:**
- [ ] **Step 1: 逐字复刻 CI 门禁命令**：
  - `python3 -m mypy --strict delector tools`
  - `python3 -m mypy --follow-imports=skip tests`
  - `python3 -m ruff check .`
  - `cd agent && go test ./... -count=1 && gofmt -l .`
- [ ] **Step 2: 跑关联测试套件与全量定向冒烟**：
  - `python3 -m pytest tests/test_bench_token_distribution.py -v`
  - `python3 -m pytest tests/test_ai_polish_loop.py -v`
  - `python3 -m pytest tests/test_server.py -k "test_ai_polish" -q`
- [ ] **Step 3: 文件格式与卫生守卫**：
  - 确保全文件纯 CRLF，0 lone LF。
- [ ] **Step 4: 追加 `WORKMEMORY/work.log` DONE 事件**。
- [ ] **Step 5: 推送分支并创建 GitHub PR**。

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1: 是否下调 `CHARS_PER_TOKEN_ESTIMATE`]**：当前假设 3.0 为保守估计（高估 token 消耗使预算提前咬合）。若实测表明德文 A1 的字符/Token 比率稳定在 2.3~2.8 之间，下调该常数至更紧凑的值是否会导致个别极端生词溢出？待 Task 2/5 产出具体分位数与越界样本后再行裁决，暂不投机修改代码常量数值。
- **[Unknown 2: 真实多轮重试下的长尾耗时]**：若真实模型在第 2 轮遇到多项复杂语法错误，其生成 token 数是否会显著膨胀？待 Task 5 回测数据揭示。

---

## 🚫 Out of Scope

- 引入 `tiktoken`、`transformers`、`huggingface` 等外部分词依赖（维持 ADR-0001 §1 零新依赖红线）。
- 修改 `llm_client.py` 的公共函数签名默认值（`include_usage` 维持 opt-in 默认 `False`，绝不改坏既有外部测试与批处理调用）。
- 在自动化 CI 运行中进行真实 LLM 出网网络调用（单测全走 stub 或静态 fixture，真跑隔离在 Task 5 HITL 阶段）。
