# Android 主分析路径统一为 spaCy Implementation Plan

> **Goal**: 把 Android 主分析路径从纯 Python 降级改为 spaCy 惰性加载（本地三级回退、失败硬失败、禁止运行期下载），并与 `syntax_tree` 共用同一加载器；用可测的数字记录改造代价。
> **Tech Stack**: Python 3.11 / spaCy 3.8 / pytest / Android Chaquopy（Gradle 8.6 + AGP 8.4.2）
> **Spec Reference**: `docs/specs/2026-11-06-android-spacy-parity-spec.md`；`docs/adr/2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md`
> **Global Constraints**:
> - 实施轮（2026-11-06）：T1–T4、T7、T8 已执行；T5/T6 因用户暂不开模拟器阻塞。T8 的产物已经 PR #237 合入 `master`（merge commit `7073bac`）。
> - 不改 schema/协议；桌面端行为不变；模型档位仍为 `de_core_news_sm`（ADR-0027）。
> - Android 运行期**禁止** `spacy.cli.download`/pip 子进程/联网；门控必须在 `_load_model_with_autodownload()` 内部。
> - 加载失败**硬失败**，不得回退纯 Python（No-Silent-Failure）。
> - 不默认重算 Android 存量纯 Python 文章；必须在 PR"已知边界"写明。
> - 不碰 9 个外部修改文件与未跟踪的 `docs/reviews/2026-11-05-code-quality-decoupling-review.md`。
> - 不 force push、不改历史、不直推 master。
> **Branch**: `fix/android-spacy-parity` — opened from `master` before Task 1。落地经过三次合并：PR #235 先把 T1–T4/T7 合入 `master`（`b13eb68`）；PR #236 的 `model_loader` 抽取误合入本分支（`dd08a95`）；PR #237 再把本分支整体合入 `master`（`7073bac`，2026-11-06），至此全部产物在 `master`。均为 merge commit，不 squash。

---

## [NOTE] Decisions So Far

- **U2 已拍板**：统一为 spaCy。判据：**宁漏勿错**——缺字段可接受，标错词性/格位不可接受。
- **ADR-0028（重写）**：Android 主路径使用 `de_core_news_sm`，惰性加载；本地三级回退；失败硬失败；禁止下载。
- **Spec（重写）**：`docs/specs/2026-11-06-android-spacy-parity-spec.md`。
- **两层口径**：通过统一加载器消除；实施完成前仍是过渡态。
- **存量数据**：默认不重算（同 `3.5.0`，惰性迁移不命中）。
- **新增测试不建新文件**：全部放进既有 `tests/test_server_android_fallback.py`，避免 CI 分片遗漏。

---

## [NOTE] Repo Invariants Pointer

每个 subagent brief 引用而不复述：`AGENTS.md`（文档路由）、`CLAUDE.md`（工程规范与避坑检索）、`.agent-rules.md`（红线）。本计划额外钉住：

- 红线 1：运行期模型加载失败是**硬失败不降级**（`model_loader.py` 的 `_resolve_nlp_model()`；2026-11-06 二次重构前位于 `processor.py:144-161`）。
- 历史不可改写：ADR-0006/0007/0027、CHANGELOG、WORKMEMORY 归档、归档计划只读。
- 测试分片：修改 `tests/test_server_android_fallback.py` 不改变文件归属；不新建 `test_*.py`。
- Android 打包：`build.gradle` 的 `extractPackages "spacy", "thinc", "de_core_news_sm"` 不得移除。

---

## [NOTE] Active Frontier (Unblocked Tasks)

**Task Dependencies**：

- T1（文档/ADR 随 PR 提交）→ T2
- T2（RED）→ T3
- T1 → T5（基线测量，原定必须在 T3 改代码前；**当前 T5 被用户阻塞**：暂不开模拟器，T3 先落地，基线缺失已记录在 ADR-0028 §4.2）
- T3（GREEN processor）→ T4（GREEN syntax_tree）
- T4 → T6（改造后测量）
- T4 → T7（具名变异）
- T6、T7 → T8（全量验证与 PR）

**File-Occupancy Partitioning（无共享写集）**：

| Task | Exclusive write set |
| --- | --- |
| T1 | `docs/adr/…-0028-…spacy-lazy-load.md`、`docs/specs/…-spacy-parity-spec.md`、`docs/plans/…-spacy-parity.md`、`docs/agents/architecture.md`、`docs/agents/android-local-runtime.md` |
| T2 | `tests/test_server_android_fallback.py` |
| T3 | `delector/nlp_engine/processor.py` |
| T4 | `delector/nlp_engine/syntax_tree.py`、`tests/test_server_android_fallback.py`（一致性测试，T2 完成后） |
| T5 / T6 | 只读测量（命令 + 记录），不写源码 |
| T7 | 只读变异（临时改后还原） |
| T8 | 只读验证 + git/PR |

> T4 与 T2 都写同一个测试文件：T4 必须在 T2 提交后串行执行，不得并行。

---

### Task 1: 文档与 ADR 随 PR 提交 [Tier: 1-Light] [Mode: AFK] [Role: Docs Verifier]

**Files:**
- Verify: `docs/adr/2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md`
- Verify: `docs/specs/2026-11-06-android-spacy-parity-spec.md`
- Verify: `docs/agents/architecture.md:118-130`
- Verify: `docs/agents/android-local-runtime.md:130-140`
- Delete (old, untracked): `docs/adr/2026-11-06-adr-0028-android-main-path-pure-python-degradation.md`、`docs/specs/2026-11-06-android-pure-python-degradation-spec.md`、`docs/plans/2026-11-06-android-pure-python-degradation-docs.md`

**Interfaces:**
- Consumes: 实际 `docs/adr/` 最大编号 0027（本 ADR 仍为 0028）。
- Produces: 无旧路径引用的文档集合；ADR/spec 互引；`docs/agents` 两处指向新 ADR。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: History-Immutable]`: 不改写 ADR-0006/0007/0027、CHANGELOG、WORKMEMORY 归档。
- [x] `[Instinct: No-Old-Path]`: 全仓 grep 不得再出现 `android-pure-python-degradation` / `android-main-path-pure-python-degradation`（例外：本计划与 spec 的删除指令/“前身”说明；不得出现在 `docs/agents`、`docs/adr` 或其它计划里）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 文档与 ADR 落位。
> Mode: AFK | Role: Docs Verifier
> Goal: 确认新 ADR-0028（spacy-lazy-load）与 spec（spacy-parity）存在且互引；`docs/agents` 两处指向新 ADR；旧纯 Python 文档已删除。
> Commands: `git grep --untracked -n "android-pure-python-degradation\|android-main-path-pure-python-degradation" -- docs/agents docs/adr`（期望空；本计划与 spec 的“前身/删除”说明不计）；`git grep --untracked -n "ADR-0028" -- docs`（期望 ≥3 文件）。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + stdout snippet)."

**Step Breakdown:**
- [x] **Step 1**: 确认新 ADR/spec 文件存在；旧三份未跟踪文件已删除。
- [x] **Step 2**: `git grep --untracked -n "android-pure-python-degradation\|android-main-path-pure-python-degradation" -- docs/agents docs/adr` 期望空（本计划/spec 的“前身/删除”说明不计）。
- [x] **Step 3**: `git grep --untracked -n "ADR-0028" -- docs` 期望命中 ADR/spec/architecture/android-local-runtime。
- [x] **Step 4**: 记录 exit code；按语义提交（实际拆成 4 个提交，见 Deviation Table）。

---

### Task 2: RED 测试先行 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tests/test_server_android_fallback.py:87-118`

**Interfaces:**
- Consumes: `from delector import server` → `server.NLP_ENGINE`；`ANDROID_ROOT=/system`；`processor._android_runtime`。
- Produces: 四条新/改测试（见下），全部在既有文件内；无生产接口变更。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: RED-First]`: 新测试必须在当前代码上真实变红，不得先改生产代码再补测试。
- [x] `[Instinct: No-New-File]`: 不新建 `test_*.py`，避免 CI 分片遗漏。
- [x] `[Instinct: Guard-Message]`: 第 118 行断言改为 `ENGINE=spacy`，失败消息写明"这是 ADR-0028 决策，不是回归"。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: 写 RED 测试。
> Mode: AFK | Role: TDD Builder
> Goal: 在 `tests/test_server_android_fallback.py` 中加入/修改以下测试，并在当前代码上确认全部变红：
> 1. `test_android_import_selects_lazy_spacy_not_none`（子进程 ANDROID_ROOT，patch spacy.load 哨兵；断言导入成功、NLP_ENGINE=='spacy'、nlp is not None、导入期哨兵未调用）
> 2. `test_android_runtime_load_never_downloads`（patch _load_spacy_model 抛错 + spacy.cli.download 哨兵；断言 RuntimeError 且哨兵未调用）
> 3. `test_android_load_failure_is_loud_not_pure`（断言抛错且不返回纯 Python 结果）
> 4. 更新第 118 行：assert 'ENGINE=pure_python' → assert 'ENGINE=spacy'，保留无下载断言，失败消息指向 ADR-0028。
> Target Files: Modify `tests/test_server_android_fallback.py:87-118`。
> Verify: `pytest tests/test_server_android_fallback.py -q` 期望至少 3 条失败；记录失败断言原文。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + failure assertion snippets)."

**Step Breakdown:**
- [x] **Step 1 (RED)**: 写 3 条新测试 + 改第 118 行断言。
- [x] **Step 2 (Verify RED)**: `pytest tests/test_server_android_fallback.py -q`；记录失败项与断言原文。
- [x] **Step 3**: 确认失败原因是"当前 Android 走 pure_python"，不是测试自身写错（如环境变量未生效）。
- [x] **Step 4 (Commit)**: 原子提交测试改动。

---

### Task 3: GREEN — processor 切换为惰性 spaCy + 下载门控 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/nlp_engine/processor.py:240-246`（删除平台分支）
- Modify: `delector/nlp_engine/processor.py:96-114`（Android 本地-only 门控；2026-11-06 二次重构后该实现迁至 `model_loader.py`）

**Interfaces:**
- Consumes: `_LazyNlp`、`_load_spacy_model`、`_android_runtime`。三者实施时在 `processor.py`（`218-228`/`35-77`/`93`）；2026-11-06 二次重构后实现迁至 `model_loader.py`（`processor` 保留转发入口）。
- Produces: Android 导入期 `nlp = _LazyNlp()`、`NLP_ENGINE = "spacy"`；`_load_model_with_autodownload()` 在 `_android_runtime` 时只走本地加载，不进入 `from spacy.cli import download`。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: Download-Gate-Inside]`: 门控必须在 `_load_model_with_autodownload()` 内部；删除平台分支后，该函数首次对 Android 可达。
- [x] `[Instinct: No-Silent-Fallback]`: 本地加载失败必须抛 `RuntimeError`，不得回退纯 Python。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: GREEN processor。
> Mode: AFK | Role: TDD Builder
> Goal:
> 1. 删除 `processor.py:240-246` 的 `elif _android_runtime:` 整段，让 Android 落入 `else: nlp = _LazyNlp()`。
> 2. 在 `_load_model_with_autodownload()`（实施时 `processor.py:96-114`；2026-11-06 二次重构后位于 `model_loader.py`）开头加 Android 本地-only 门控：
>    `if _android_runtime: return _load_spacy_model(SPACY_MODEL_NAME)`（失败直接抛 RuntimeError，不下载）。
> Constraints: 不改 `_load_spacy_model` 的三级回退；不改 `_resolve_nlp_model` 的双检锁；不改桌面下载兜底语义。
> Verify: `pytest tests/test_server_android_fallback.py -q` 全绿；`git grep -n "spacy.cli import download" delector/nlp_engine/processor.py` 仍只在桌面分支可达。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + pass count)."

**Step Breakdown:**
- [x] **Step 1 (GREEN)**: 删除平台分支；Android 落入 `_LazyNlp`。
- [x] **Step 2 (GREEN)**: `_load_model_with_autodownload` 加 Android 本地-only 门控。
- [x] **Step 3 (Verify GREEN)**: `pytest tests/test_server_android_fallback.py -q` 全绿。
- [x] **Step 4 (Refactor)**: 更新 `processor.py:38-42`、`:241-243`、`:246` 的失效理由注释与展示字符串（"无 dist-info"删除）。
- [x] **Step 5 (Commit)**: 原子提交。

---

### Task 4: GREEN — syntax_tree 加载器收敛 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `delector/nlp_engine/syntax_tree.py:71-89`
- Modify: `tests/test_server_android_fallback.py`（新增一致性测试）

**Interfaces:**
- Consumes: `model_loader._load_spacy_model(SPACY_MODEL_NAME)`；`get_spacy_load_error()` / `_spacy_load_error`。（实施时经 `processor` 转发；2026-11-06 二次重构后 `syntax_tree` 直接依赖 `model_loader`。）
- Produces: `syntax_tree.get_spacy_nlp()` 返回与主路径同一加载器加载的模型；保留错误诊断。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: One-Loader]`: 不得保留两套 `spacy.load`；`syntax_tree` 只调用统一加载器（现为 `model_loader._load_spacy_model`，实施时经 `processor` 转发）。
- [x] `[Instinct: Diagnostics-Preserved]`: `_spacy_load_error` 仍要能反映失败原因，供 `/api/syntax/spacy-status` 使用。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: GREEN syntax_tree。
> Mode: AFK | Role: TDD Builder
> Goal: 把 `syntax_tree.py:84` 的 `spacy.load(SPACY_MODEL_NAME)` 改为统一加载器（实施时经 `processor._load_spacy_model` 转发；2026-11-06 二次重构后直接依赖 `model_loader`）；保留 `_spacy_load_error` 诊断语义；新增 `test_processor_and_syntax_tree_share_engine_status`。
> Constraints: 不改 `analyze_sentence_topology` 的公开签名与返回结构；不反向 import 造成环（二次重构后两条边都单向指向 `model_loader`）。
> Verify: `pytest tests/test_server_android_fallback.py tests/test_syntax_tree.py -q` 全绿。
> Return: Summary with MANDATORY Physical Execution Receipt (exit code + pass count)."

**Step Breakdown:**
- [x] **Step 1**: 在 `syntax_tree.py` 顶部 import 统一加载器（实施时 `from .processor import _load_spacy_model`；2026-11-06 二次重构后改为 `from . import model_loader`）。
- [x] **Step 2**: 替换 `spacy.load(SPACY_MODEL_NAME)`，保留异常写入 `_spacy_load_error`。
- [x] **Step 3**: 加 `test_processor_and_syntax_tree_share_engine_status`（同进程两端引擎状态一致）。
- [x] **Step 4 (Verify GREEN)**: `pytest tests/test_server_android_fallback.py tests/test_syntax_tree.py -q` 全绿。
- [x] **Step 5 (Commit)**: 原子提交。

---

### Task 5: 基线测量（改代码前）[Tier: 3-Critical] [Mode: HITL] [Role: Measurement] [Status: blocked-by-user（未开模拟器）]

> **状态（2026-11-06）**：用户明确暂不开模拟器，T5 未执行。因此 ADR-0028 §4.2 的三项 Android 代价均标记为 `未测量`；本轮只交付 T1–T4。

**Files:**
- Read-only: 模拟器 `emulator-5554`、当前 `assembleEmulatorDebug` APK
- Record: `docs/adr/2026-11-06-adr-0028-android-main-path-spacy-lazy-load.md` §4.2（T6 后统一写入）

**Interfaces:**
- Consumes: `docs/agents/android-local-runtime.md` §3 的构建/装机/端口转发流程。
- Produces: 基线数字（纯 Python 主路径）：冷启动 `/api/health` 首响、首次分析墙钟、`am start -W TotalTime`、RSS。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Baseline-Before-Code]`: 基线必须在 T3 改代码前采集；否则无法比较。
- [ ] `[Instinct: Real-Numbers]`: 记录命令与原始输出，不得凭印象写数字。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 采集改造前基线。
> Mode: HITL | Role: Measurement
> Goal: 在当前 APK（纯 Python 主路径）上记录四项指标。
> Commands:
> - `adb shell am start -W -n org.delector.app.emulator/org.delector.app.MainActivity`
> - `Measure-Command { Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing }`
> - 用现有导入接口导入一句 V2 主句，记录首次分析墙钟
> - `adb shell dumpsys meminfo org.delector.app.emulator`
> Constraints: 只读测量；不改代码；模拟器使用登记表补一行。
> Return: Summary with MANDATORY Physical Execution Receipt (raw numbers + command outputs)."

**Step Breakdown:**
- [ ] **Step 1**: 按 §3 构建/装机/启动，登记模拟器使用。
- [ ] **Step 2**: 记录 `am start -W` TotalTime。
- [ ] **Step 3**: 记录 `/api/health` 首响墙钟。
- [ ] **Step 4**: 导入 V2 主句，记录首次分析墙钟。
- [ ] **Step 5**: 记录 RSS（`dumpsys meminfo`）。
- [ ] **Step 6**: 把原始数字暂存到任务回执（T6 统一写入 ADR）。

---

### Task 6: 改造后测量（GREEN 完成后）[Tier: 3-Critical] [Mode: HITL] [Role: Measurement] [Status: blocked-by-user（依赖 T5）]

> **状态（2026-11-06）**：T5 未执行 ⇒ T6 同样未执行；ADR-0028 §4.2 保持 `未测量`，未用桌面基准顶替。

**Files:**
- Read-only: 模拟器、GREEN 后的 APK
- Modify: ADR-0028 §4.2（写入前后对比）

**Interfaces:**
- Consumes: T3/T4 的 GREEN 代码；T5 的基线数字。
- Produces: 改造后数字 + 差值；写入 ADR-0028 §4.2 与 PR 描述。

**SSOT Effect:** —

**Injected Instincts:**
- [ ] `[Instinct: Honest-Delta]`: 数字不好看也照实写，不得调阈值/基线。
- [ ] `[Instinct: Trigger-Check]`: 若耗时/内存超预估，触发 ADR-0028 §6 复审，而不是悄悄接受。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 6: 采集改造后数据并写 ADR。
> Mode: HITL | Role: Measurement
> Goal: 重复 T5 的四项指标（spaCy 主路径），把前后对比写入 ADR-0028 §4.2。
> Constraints: 不改阈值；若超预估，记录并触发复审；不粉饰。
> Return: Summary with MANDATORY Physical Execution Receipt (before/after table + ADR diff)."

**Step Breakdown:**
- [ ] **Step 1**: 重新构建/装机 GREEN APK。
- [ ] **Step 2**: 重复 T5 四项测量。
- [ ] **Step 3**: 计算差值；写入 ADR-0028 §4.2。
- [ ] **Step 4**: 若超出可接受范围，标记复审触发。

---

### Task 7: 具名变异验证 [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Temporary modify then restore: `delector/nlp_engine/processor.py`、`delector/nlp_engine/syntax_tree.py`

**Interfaces:**
- Consumes: T2 的测试、T3/T4 的 GREEN 代码。
- Produces: 四条变异的红/绿证据；工作树最终恢复 GREEN。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: Mutation-Evidence]`: 每条变异必须记录失败断言原文；还原后必须复绿。
- [x] `[Instinct: No-Residual]`: 变异不得留在工作树；用 `git diff` 确认还原。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 7: 五条具名变异。
> Mode: AFK | Role: TDD Builder
> Mutations:
> 1. `processor.py` 平台分支改回 `nlp = None` → `test_android_import_selects_lazy_spacy_not_none` 应红。
> 2. 允许 Android 走 `spacy.cli.download` → `test_android_runtime_load_never_downloads` 应红。
> 3. 本地加载失败时返回纯 Python 结果 → `test_android_load_failure_is_loud_not_pure` 应红。
> 4. `syntax_tree` 改回裸 `spacy.load` → `test_processor_and_syntax_tree_share_engine_status` 应红。
> 5. `syntax_tree` 加载失败回退纯 Python（A7）→ `test_syntax_tree_load_failure_is_loud_not_pure` 应红。
> Each: apply → run targeted test → record failure → revert → run green.
> Verify: `git diff` 最终为空（相对 T4 提交）。
> Return: Summary with MANDATORY Physical Execution Receipt (5 red outputs + 5 green outputs)."

**Step Breakdown:**
- [x] **Step 1-5**: 逐条应用变异、跑定向测试、记录失败、还原、复绿（5/5 均被抓）。
- [x] **Step 5**: `git diff` 确认无残留。
- [x] **Step 6 (Commit)**: 变异无正式改动，无需提交（工作树干净）。

---

### Task 8: 全量验证与 PR [Tier: 1-Light] [Mode: AFK] [Role: Release Verifier]

**Files:**
- Verify: `delector/nlp_engine/processor.py`、`delector/nlp_engine/syntax_tree.py`、`tests/test_server_android_fallback.py`
- Verify: `docs/adr/…`、`docs/specs/…`、`docs/agents/…`

**Interfaces:**
- Consumes: Tasks 1-7 的产物。
- Produces: 一个 PR，描述含"已知边界"（未真机验证 / 存量未重算 / 低端机 OOM 未测 / 首次加载数字）。

**SSOT Effect:** —

**Injected Instincts:**
- [x] `[Instinct: Evidence]`: 不写"全量验证通过"而不给命令与输出。
- [x] `[Instinct: Known-Boundaries]`: PR 必须如实登记未验证项。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 8: 全量验证与 PR。
> Mode: AFK | Role: Release Verifier
> Commands:
> - `pytest tests/test_server_android_fallback.py tests/test_syntax_tree.py tests/test_nlp_model_sm_only.py -q`
> - `pytest tests -q`
> - `ruff check delector tests tools`
> - `mypy --follow-imports=skip delector`
> - `git grep -n "无 dist-info" delector/nlp_engine/processor.py`（期望空）
> - `git status --porcelain`
> Constraints: 不 force push、不改历史、不直推 master；PR 用 merge commit，不 squash。
> Return: Summary with MANDATORY Physical Execution Receipt (exit codes + pass counts + git status)."

**Step Breakdown:**
- [x] **Step 1**: 跑定向与全量测试，记录 passed/skipped。
- [x] **Step 2**: 跑 ruff/mypy，记录结果。
- [x] **Step 3**: 跑文档一致性 grep。
- [x] **Step 4**: `git status --porcelain` 确认只含预期文件。
- [x] **Step 5**: 推送分支并开 PR（PR #235 继续用，不合并）。
- [x] **Step 6**: PR 描述补"已知边界"与测量数字。

---

## [NOTE] Fog of War (Not Yet Specified)

- **[Unknown 1] Android 首次加载耗时/内存的可接受阈值**：需 T5/T6 实测后写入 ADR-0028 §6；在此之前阈值未定。
- **[Unknown 2] arm64 真机行为**：本机无设备；不得用 x86_64 模拟器结果替代。
- **[Unknown 3] 低端机 OOM 基线**：无设备样本；只能记录目标模拟器 RSS，不能外推。

---

## [NOTE] Deferred Gap Register

| gap | why deferred | trigger that forces revisiting | owner |
| --- | --- | --- | --- |
| Android 存量纯 Python 文章未重算 | 同 `3.5.0`，惰性迁移不命中；默认不重算 | 用户要求历史文章一致，或移动端上线后反馈 | Haoyu Xi |
| arm64 真机验证 | 本机无 arm64 设备 | 有可用设备时 | maintainer |
| 首次加载耗时/内存阈值 | 需实测后才能定 | T5/T6 测量完成 | Haoyu Xi |
| B9 五级链 L3/L5 零命中 | 需 `Token` fixture 反证不可达 | 下一次死代码清理专项 | maintainer |
| Android 更新 chip / PWA | 阻塞于真机与 HTTPS 假设 | 有真机与 HTTPS 环境 | maintainer |

---

## [NOTE] Deviation Table (post-execution, filled before merge)

| plan text | what was actually built | why |
| --- | --- | --- |
| T1 之后由 T8 统一提交 | 按语义拆成 4 个提交（`f4c09d7` docs / `ea8b6ee` tests / `af027f8` processor / `2f79ccb` syntax_tree） | 用户要求每完成一项立即提交，便于逐项审查 |
| D4 只覆盖主分析路径 | A7 扩到所有 spaCy 调用点：`analyze_syntax_tree` 失败抛 `RuntimeError` | 用户 2026-11-06 拍板「覆盖」；纯 Python 句法树同属"错误标注" |
| 计划以 PR #235 一次落地 | 实际三次合并：#235 先入 `master`（`b13eb68`）；#236 的 `model_loader` 抽取误合入 `fix/android-spacy-parity`（`dd08a95`）；#237 再把分支整体合入 `master`（`7073bac`，2026-11-06） | #235/#236 合并顺序错位；#237 把 `model_loader` 补齐到 `master` |
| 加载器实现留在 `processor.py` | 2026-11-06 二次重构抽出 `delector/nlp_engine/model_loader.py`；`processor` 只保留转发入口与兼容代理，`syntax_tree` 直接依赖 `model_loader` | 消除 `processor` ↔ `syntax_tree` 的双向依赖（函数内 import 藏环） |

---

## [NOTE] Out of Scope

- 历史数据重算/版本号升级（默认不做）。
- 模型档位变更（ADR-0027）。
- 真机（arm64）验证。
- 删除 B9 五级链的 L3/L5。
- Android 更新 chip / PWA 安装提示。
