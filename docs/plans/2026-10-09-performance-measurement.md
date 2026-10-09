# 性能测量基线（ADR-0018 D1）Implementation Plan

> **Goal**: 用**可复跑**的基准回答「Python 是否、在哪里拖垮项目」，产出各层占比，并按 ADR-0018 §6 的判定门给出走 O0/O2/O3 的结论
> **Tech Stack**: Python 3.11（`time.perf_counter` / `sqlite3` / `tempfile`）、pytest 门禁、CI（`BENCH_SCALES` / `BENCH_ROUNDS` 快档）
> **Spec Reference**: [ADR-0018](../../docs/adr/2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md) §6（1 小时最小测量方案）、§3（选项与翻盘条件）
> **Global Constraints**:
> - **复用既有范式（Ladder 1）**：`tools/bench_cards_endpoint.py`（四段分解 + `tempfile.mkdtemp()` 隔离 + **中位数**而非均值 + `_verdict()` 阈值结论）与 `tests/test_cards_endpoint_cost.py`（存在性 / 隔离源码断言 / 分段标签 / 占比开区间 / **B>A 且 B>C** 防恒真）。新基准 MUST 与之同构。
> - **隔离纪律（`[Instinct: Isolated-DB]`）**：`DELECTOR_DATA_DIR` / `DATABASE_PATH` / `PROGRESS_DB_PATH` **必须在 import delector 之前**设好（`database.py` 导入期就 `makedirs .cache/audio`），`finally` 清理。**绝不触碰仓库根真实 `delector.db`**。
> - **计时纪律**：`MIN_ROUNDS = 5`，取**中位数**（单轮会被 GC/磁盘/页面缓存污染）。
> - **与生产一致**：不跑 `ANALYZE`（生产路径无人执行，跑了会让计划偏乐观）。
> - **每个新基准 MUST 配一个 `tests/test_*.py` 门禁**，且门禁必须**防恒真**（断言段间差异/占比区间，而不是"能跑就绿"）。
> - **阈值优先钉相对量**（占比、`per_row_us`），绝对毫秒只作参考不钉 —— CI 机器噪声会让绝对阈值成为假红来源。
> - **本计划不改任何生产代码**（只在 `tools/` 加基准、在 `tests/` 加门禁、在 `docs/` 回填结论）。禁 `# type: ignore`；两道 mypy 必须干净。
> - 提交禁 `--no-verify`；本计划**不发版**。

---

## 🏛️ Decisions So Far

- **ADR-0018**（accepted 2026-10-09）：**先测量、不换主体**。Python CPU 占比 > 50% **且** p95 > 2 倍目标 ⇒ 走 O2（热点下沉）；编排/并发主导 ⇒ 走 O3（扩展 ADR-0008 边界）；**O1（换 HTTP 主体）已永久否决**（三条依据 + 三条翻盘条件见 ADR §3.2）。
- **D1 复用而非新建范式**：现有 `bench_cards_endpoint.py` 已是一份成熟基准（四段分解、隔离、中位数、verdict），本计划的新基准照它的骨架写，避免各写一套口径导致数字不可比。
- **D2 卡盒场景不新建脚本**：改现有 `bench_cards_endpoint.py` —— 它目前**只输出数字、不钉阈值**（`test_cards_endpoint_cost.py` 只断言结构与开区间），而 ADR-0018 D6 要求"新基准必须钉阈值"。且它缺 ADR 需要的**Python 侧占比**（现只有 `filesort_pct`，没有 `python_ms / D`）。
- **D3 spaCy 单价矛盾必须被收口**：`syntax_hard.py:9` 写 `~42ms/句`、审计文档写 `~2.1ms/句`（差 20 倍，都不可复跑）。Task 2 的产物是**唯一可复跑值**，并回写 ADR §1.3。
- **D4 前端层占比只做到"能测就测"**：本机无可靠的前端渲染测量手段（无浏览器自动化基线），故 Task 5 对前端层只给出**手工测量步骤 + 数据落点**，不伪造自动化数字。

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 卡盒基准补「各层占比」与阈值闸 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `d:/Code/DeLector/tools/bench_cards_endpoint.py`（输出层：新增占比行；不改四段定义与隔离逻辑）
- Modify: `d:/Code/DeLector/tests/test_cards_endpoint_cost.py`（新增阈值与占比断言）

**Interfaces:**
- Consumes: 现有 `_bench_scale()` 返回的 `A/B/C/D/lookup_ms/filesort_ms/python_ms`
- Produces: 新增输出行 `python_pct=NN.N%`（Python 物化+FSRS 占端点总耗时）、`per_row_us=NN.NN`（已存在，保持不变）、`scaling_ratio=N.NN`（已存在）；以及**门禁可解析**的 `python_pct`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Ratio-Over-Absolute]`: 门禁钉 `python_pct` 落在 `(0, 100]` 且 `per_row_us` 有上界；**不钉绝对毫秒**（CI 机器差异 ⇒ 假红）。
- [ ] `[Instinct: No-Silent-Conclusion]`: 沿用现脚本 `_verdict()` 的可判定结论风格，不得改成"输出一堆数字不给结论"。
- [ ] `[Instinct: Don't-Break-Existing-Gate]`: 现有四条断言（存在性/隔离/四段/B>A 且 B>C）**必须全部保留**，只增不改弱。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 1: 给 `GET /api/cards` 基准补各层占比与阈值闸。
> Mode: AFK | Role: TDD Builder
> Goal: 让卡盒场景能回答『Python 侧占多少』（ADR-0018 判定门的输入）。
> Target Files: Modify `tools/bench_cards_endpoint.py`（输出层）、`tests/test_cards_endpoint_cost.py`（门禁）。
> Injected Instincts: 钉比值不钉绝对时间；保留现有四条断言；结论须可判定。
> TDD Steps:
> 1. 在 `tests/test_cards_endpoint_cost.py` 写断言：输出含 `python_pct=NN.N%` 且落在 (0,100]、`per_row_us` 有上界（RED：现在没有这行）。
> 2. Run `BENCH_SCALES=8000 BENCH_ROUNDS=5 python -m pytest tests/test_cards_endpoint_cost.py -q` and verify it fails。
> 3. 在 `bench_cards_endpoint.py` 输出层新增 `python_pct` 行（GREEN）。
> 4. Run the gate + `mypy --follow-imports=skip tests` + `mypy --strict delector tools` + `ruff check .`。
> Return: MANDATORY Physical Execution Receipt (exit code + stdout snippet + `git diff --stat`)。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: Refactor & Flatten with guard clauses (REFACTOR)**
- [ ] **Step 6: Physical Evidence Gate**（原始收据：命令 + 退出码 + passed 计数 + diff）
- [ ] **Step 7: Git atomic commit**

---

### Task 2: spaCy 单价基准（收口 42ms vs 2.1ms 的 20 倍矛盾） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `d:/Code/DeLector/tools/bench_spacy_unit.py`
- Test: `d:/Code/DeLector/tests/test_spacy_unit_cost.py`

**Interfaces:**
- Consumes: `delector.nlp_engine.processor`（模型候选 `de_core_news_md` / `de_core_news_sm`，见 `processor.py:20-23`）
- Produces: 输出 `per_sentence_ms=N.NN`、`per_token_us=N.NN`、`model=<name>`、`sentences=N`、`rounds=N`；以及**可判定**结论行 `verdict=...`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Realistic-Data]`: 语料必须是**真实德语长句**（不得用 `"a b c"` 造数 —— 句长/词性分布直接决定 spaCy 耗时），且覆盖短/中/长三档句长。
- [ ] `[Instinct: Isolated-DB]`: 同现有基准的 `mkdtemp` 隔离（若需 `init_db`）。
- [ ] `[Instinct: No-Silent-Conclusion]`: 必须给出"哪个模型、什么句长下每句多少 ms"，并**明确对照** `syntax_hard.py:9` 的 42ms 与审计的 2.1ms（结论里点名这两个旧值，说明新值落在哪一侧）。
- [ ] `[Instinct: Median-Not-Mean]`: 中位数 + `MIN_ROUNDS=5`。
- [ ] `[Instinct: Model-Availability]`: `md` 未必装得上（Android/离线）—— 缺模型时**降级测 sm 并如实打印 `model=de_core_news_sm (md 不可用)`**，不得静默跳过也不得硬失败。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 2: spaCy 单价基准 `tools/bench_spacy_unit.py`。
> Mode: AFK | Role: TDD Builder
> Goal: 用可复跑脚本给出 spaCy 每句/每 token 耗时，收口『42ms/句 vs 2.1ms/句』的 20 倍矛盾。
> Target Files: Create `tools/bench_spacy_unit.py`；Test `tests/test_spacy_unit_cost.py`。
> Injected Instincts: 真实德语句料（短/中/长三档）；mkdtemp 隔离；中位数 ≥5 轮；结论必须点名对照两个旧值；md 缺失时降级到 sm 并如实标注。
> TDD Steps:
> 1. 写 `tests/test_spacy_unit_cost.py`：脚本存在、输出含 `per_sentence_ms=`/`per_token_us=`/`model=`、且 `per_sentence_ms > 0`（RED）。
> 2. Run `python -m pytest tests/test_spacy_unit_cost.py -q` and verify it fails。
> 3. 实现基准（GREEN）。
> 4. Run gate + 两道 mypy + ruff，并**人工跑一次全量**记录真实数字（写进报告）。
> Return: MANDATORY Physical Execution Receipt（含真实跑出的 per_sentence_ms 数字）。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: Run tests and verify all green**
- [ ] **Step 5: 人工跑一次，记录真实 `per_sentence_ms`（md 与 sm 各一次）**
- [ ] **Step 6: Physical Evidence Gate**
- [ ] **Step 7: Git atomic commit**

---

### Task 3: 长文精读端到端基准（冷读 vs 热读，验缓存生效） [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `d:/Code/DeLector/tools/bench_long_read.py`
- Test: `d:/Code/DeLector/tests/test_long_read_cost.py`

**Interfaces:**
- Consumes: `delector.routes.syntax_hard`（`_RANK_CACHE`、`_CACHE_TTL_SEC=300`、`invalidate_rank_cache()`，见 `syntax_hard.py:43-59`）
- Produces: 输出 `cold_ms=N.NN`、`warm_ms=N.NN`、`cache_speedup=N.NN`、`sentences=N`、`spacy_ms=N.NN`、`other_ms=N.NN`、`spacy_pct=NN.N%`

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Cache-Honesty]`: 必须**同一份材料**跑冷读与热读；若 `warm_ms >= cold_ms` 说明缓存没生效 ⇒ 结论必须如实说"缓存未生效"，不得粉饰。
- [ ] `[Instinct: Realistic-Data]`: 材料用真实德语长文（不得 `lorem ipsum`），长度取真实量级（≥ 数百 token）。
- [ ] `[Instinct: Isolated-DB]`: `mkdtemp` + 三环境变量，绝不碰仓库根 db。
- [ ] `[Instinct: Median-Not-Mean]`: 冷读/热读各 ≥5 轮取中位数（注意热读需用**新的**缓存生命周期，否则测的是同一份缓存）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 3: 长文精读端到端基准 `tools/bench_long_read.py`。
> Mode: AFK | Role: TDD Builder
> Goal: 给出长文精读的冷/热读耗时与 spaCy 在其中占多少，并验证 `_RANK_CACHE` 真的生效。
> Target Files: Create `tools/bench_long_read.py`；Test `tests/test_long_read_cost.py`。
> Injected Instincts: 同材料冷热对比；缓存未生效必须如实说；真实德语长文；隔离；中位数。
> TDD Steps: 1) RED（断言输出含 `cold_ms`/`warm_ms`/`spacy_pct`）→ 2) 验证失败 → 3) 实现 → 4) 跑门禁 + mypy + ruff → 5) 人工跑一次记录真实数字。
> Return: MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: 人工跑一次全量，记录 cold/warm 与 spacy_pct**
- [ ] **Step 5: Physical Evidence Gate**
- [ ] **Step 6: Git atomic commit**

---

### Task 4: 冷启动基准 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `d:/Code/DeLector/tools/bench_cold_start.py`
- Test: `d:/Code/DeLector/tests/test_cold_start_cost.py`

**Interfaces:**
- Consumes: `delector.server.create_app` / `init_db`；可选：`subprocess` 起 `uvicorn` 并轮询 `/api/health`（`main.py:2596`）
- Produces: 输出 `import_ms=N.NN`（import delector 耗时）、`init_db_ms=N.NN`、`app_ready_ms=N.NN`、`health_200_ms=N.NN`（若用子进程）、`model_load_ms=N.NN`（spaCy 模型首次加载）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Measure-What-User-Feels]`: 用户体感的"启动慢"是**进程起到可服务**，故优先测 `health_200_ms`（子进程真实起服务）；`import_ms`/`init_db_ms` 是归因用的分段，二者都要。
- [ ] `[Instinct: Isolated-DB]`: 子进程也要钉临时 `DELECTOR_DATA_DIR`（否则污染仓库根 `.cache/audio`）。
- [ ] `[Instinct: No-Silent-Conclusion]`: 结论必须点名 Android 侧已知口径（首启解包 ~30MB、启动页轮询上限 ~84s，见 `architecture.md:100-101`）与桌面侧的差值关系。
- [ ] `[Instinct: Flaky-Aware]`: 冷启动对磁盘缓存极敏感 ⇒ 门禁**只断言可解析与正区间**，绝对阈值交给人工档（避免 CI 假红）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 4: 冷启动基准 `tools/bench_cold_start.py`。
> Mode: AFK | Role: TDD Builder
> Goal: 量化『进程起到可服务』的各段耗时（import / init_db / 模型加载 / health 200）。
> Target Files: Create `tools/bench_cold_start.py`；Test `tests/test_cold_start_cost.py`。
> Injected Instincts: 测用户体感（health_200）+ 归因分段；临时目录隔离；结论对照 Android 已知口径；门禁只钉可解析与正区间，不钉绝对阈值。
> TDD Steps: RED → 验证失败 → GREEN → 跑门禁+mypy+ruff → 人工跑一次记录数字。
> Return: MANDATORY Physical Execution Receipt。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: 人工跑一次，记录各段**
- [ ] **Step 5: Physical Evidence Gate**
- [ ] **Step 6: Git atomic commit**

---

### Task 5: 分层剖析工具（Python CPU / RSS / SQL / 网络）+ 汇总 [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `d:/Code/DeLector/tools/bench_profile_layers.py`
- Test: `d:/Code/DeLector/tests/test_profile_layers.py`

**Interfaces:**
- Consumes: Task 1–4 的基准（可分别调用或子进程跑）
- Produces: 输出一张**分层占比表**：`python_cpu_pct` / `sql_pct` / `network_pct`（AI·TTS·RSS）/ `startup_s` / `frontend_pct`（若不可测则输出 `frontend_pct=unmeasured` 并说明），以及 `verdict=`（对照 ADR-0018 §6 判定门：Python CPU > 50% 且 p95 > 2 倍目标 ⇒ 建议 O2；否则建议 O0/O3）

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: No-Fake-Numbers]`: **测不出的层必须输出 `unmeasured` 并写明原因**，禁止用估算/占位数字填满表格（这正是 ADR-0018 §1.3 批评的"不可复跑数字"）。
- [ ] `[Instinct: SSR-Measurement]`: RSS 用 `resource`/`psutil` 二选一 —— **若无 psutil 依赖则用 stdlib `resource`（POSIX）并在 Windows 上如实标注不可用**，不得为此新增依赖（本计划不动 requirements）。
- [ ] `[Instinct: Network-Is-External]`: AI/TTS 属**外部网络**，测量必须标注"受网络波动影响"，并给出"缓存/离线时的对照值"（若无法对照则标 `unmeasured`）。
- [ ] `[Instinct: One-Command]`: 一条命令跑完全部四场景并输出可解析结果（便于人工 1 小时档与 CI 快档共用）。

**Subagent Prompt Scaffold (for /dfs-exec):**
> "Implement Task 5: 分层剖析与汇总 `tools/bench_profile_layers.py`。
> Mode: AFK | Role: TDD Builder
> Goal: 一条命令产出分层占比表 + 对照 ADR-0018 判定门的 verdict。
> Target Files: Create `tools/bench_profile_layers.py`；Test `tests/test_profile_layers.py`。
> Injected Instincts: 测不出就输出 unmeasured 并写原因（禁止伪造数字）；不新增依赖（RSS 无 psutil 则如实标注）；网络层标注外部波动；一条命令跑完。
> TDD Steps: RED → 验证失败 → GREEN → 跑门禁+mypy+ruff → 人工跑一次把分层表贴进报告。
> Return: MANDATORY Physical Execution Receipt（含真实分层表）。"

**Step Breakdown:**
- [ ] **Step 1: Write the failing test (RED)**
- [ ] **Step 2: Run test and verify it fails with expected message**
- [ ] **Step 3: Implement minimal production code (GREEN)**
- [ ] **Step 4: 人工跑一次，产出分层占比表**
- [ ] **Step 5: Physical Evidence Gate**
- [ ] **Step 6: Git atomic commit**

---

### Task 6: 结论回填 ADR + 门禁收口 + 分支交付 [Mode: HITL] [Role: Release Steward]

**Files:**
- Modify: `d:/Obsidian/Coding/08-Projects/DeLector/01-ADR/0018-performance-measurement-before-runtime-swap.md`（§1.3 表换成本次可复跑数字；§4 标记 D1 已执行；写入 D2 的路线结论）
- Modify: `d:/Code/DeLector/docs/adr/2026-10-09-adr-0018-performance-measurement-before-runtime-swap.md`（仓内副本同步，从 vault 机械同步）
- Modify: `d:/Code/DeLector/WORKMEMORY/work.log`、`WORKMEMORY/PROJECT_OVERVIEW.md`

**Interfaces:**
- Consumes: Task 1–5 的实测数字
- Produces: ADR §1.3 的可复跑数字表 + **路线结论**（O0 / O2 / O3 三选一，附判定依据）+ work.log 事件

**Injected Instincts (Compile-Time Rule Injection):**
- [ ] `[Instinct: Measurement-From-Own-Run]`: 回填数字 MUST 来自**本次最终 commit 的本人实跑**，不得抄子代理报告（v5.16.0 的 1048 vs 1053 教训）。
- [ ] `[Instinct: No-Truncated-Verification]`: 核验输出禁 `head`/`tail` 截断（会漏看失败项且吃掉退出码）。
- [ ] `[Instinct: Verdict-Must-Be-Decidable]`: 结论必须落到 O0/O2/O3 之一；若数据不足以判定，写明"不足以判定 + 还缺哪一次测量"，**不得停在"需要进一步分析"**。

**Subagent Prompt Scaffold (for /dfs-exec):**
> 本任务**不派 AFK 子代理**（HITL：需要编排者判断与人工跑数）。按下列步骤执行并回报原始输出。

**Step Breakdown:**
- [ ] **Step 1: 全量门禁**（半 A + 半 B + 全部 `tools/*_probe.mjs` 探针 + `ruff` + 两道 mypy）；**额外跑一次人工档**（默认 scales，非 CI 快档）取最终数字
- [ ] **Step 2: 把数字回填 ADR §1.3**（替换"证据不足"行）+ §4 标记 D1 已执行 + 写 D2 路线结论
- [ ] **Step 3: 仓内副本从 vault 机械同步**（行级 + 破坏检测）
- [ ] **Step 4: work.log 事件 + PROJECT_OVERVIEW 待办更新**
- [ ] **Step 5: Physical Evidence Gate**（原始门禁收据 + 分层表）
- [ ] **Step 6: Git atomic commit**（本分支；**不发版**）

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown 1] 前端渲染层占比如何测**：本机无浏览器自动化基线（无 Playwright/Puppeteer 依赖，且本计划不动 requirements）。⇒ Task 5 对前端层输出 `frontend_pct=unmeasured` 并给**手工测量步骤**（Chrome DevTools Performance 录一段卡盒滚动）。若将来要自动化，需先解决依赖与稳定性，另开决策。
- **[Unknown 2] Android 侧测量**：本机无 Android SDK（Java 侧只能靠 CI 验证），真机冷启动/首启解包 30MB 无法在本机量化 ⇒ Android 数字留空并标注，不在本计划伪造。
- **[Unknown 3] AI/TTS 网络层的可重复性**：外部依赖（DeepSeek / Edge TTS），网络波动大 ⇒ 只给"当时值 + 标注"，不钉阈值。
- **[Unknown 4] 若结论走 O2（热点下沉），Android arm64 交叉编译链路未定** ⇒ 不在本计划内，测量完成后另开 ADR/计划。

---

## 🚫 Out of Scope

- **不做**热点下沉（O2 的实施）、**不做** ADR-0008 边界扩展（O3 的实施）—— 本计划只产出"走哪条路"的结论
- **不改任何生产代码**（`delector/`、`static/`、`android/` 一律不动）
- **不换 HTTP 主体**（ADR-0018 D3 已永久否决）
- **不引入新依赖**（RSS 测量无 `psutil` 则如实标注 `unmeasured`）
- **不发版**
