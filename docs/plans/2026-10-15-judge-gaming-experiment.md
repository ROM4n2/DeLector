# §4.3 第 8 条对照实验（浅裁判是否真被模型针对）实施计划

> **Goal**: 把 `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` 的设计落成**可复跑的确定性 harness**，并跑出能分别证伪 P1（奖励黑客）/**P2（真变好）** 的原始数据；结论用于决定 §4.3 的无条件「已实现」能否解禁（当前：**禁用**，见 ADR-0023 §11.3）。
> **Tech Stack**: Python 3.11 / pytest（无 pytest-asyncio）/ 复用 `run_polish_loop` 的注入缝 + `llm_client.chat`；真跑需真实 `DEEPSEEK_API_KEY`
> **Spec Reference**: `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md`（设计稿，含判决量定义）· ADR-0023 §4.3 与 §11.3/§11.6 · `01-Rules/AGENT-EVALUATION-HARNESS.md` §1/§3 · `01-Rules/AGENT-CONDUCT.md` §10.2
> **Global Constraints**:
> - **密钥安全（MUST）**：密钥只经**应用自身**的 `delector.server.load_env()` 载入（实测：载入后 `os.environ` 与 `get_effective_api_key()` 均非空）。**MUST NOT** 打印、写入文件、进日志、进提交、进报告 —— 报告与测试输出里只允许出现**布尔**或长度。仓库 secret-scan 预提交门禁是最后一道防线，不是第一道。
> - **测试零 Key 红线（MUST）**：harness MUST 提供 `--dry-run`（stub chat）；**全部测试用例在无 Key 环境下必须能跑**；真跑属 HITL 步骤（Task 5/6），不得写进 pytest。
> - **判决只用确定性真值（MUST）**：按 `AGENT-EVALUATION-HARNESS` §1，判决量 = 仪器 A（held-out 种子错误的确定性回收率）；LLM rater 是**辅助信号**，MUST NOT 参与 P1/P2 判定，报告里必须逐处标注。
> - **单变量与成本记账（MUST）**：按 §3.2/§3.3 —— 三臂严格单变量（A1→A2 = 轮数；A2→A3 = 裁判信号），共用同一 task 模板/`system_prompt` 规则/`temperature`，**逐篇交错执行**；报告 MUST 同时给 Token 成本、p50/p95 延迟、平均轮数。
> - **预注册（MUST）**：阈值在 pilot（N=5）后**固定并回写设计稿**，主实验不得改；样本集冻结（样本外发现另列）；剔除文本的唯一正当理由是"文本本身构造错误"且须写明。
> - 零新依赖 / 行尾 CRLF / `ruff check .` 零告警 / mypy 按所在档 / 中文注释；**不接线、不改生产代码路径**（只读 `run_polish_loop` 的注入缝）。
> **Branch**: `feat/judge-gaming-experiment`（从 `master` 开；实现类任务全部经 PR 落地）

---

## 🏛️ Decisions So Far

| # | 决策 | 依据 |
| --- | --- | --- |
| D1 | **判决量只有一个**：held-out 种子错误的确定性回收率 `R_uncovered`；`R_judge` 与 LLM 盲评分都是旁证 | `AGENT-EVALUATION-HARNESS` §1 (MUST) + `AGENT-CONDUCT` §10.2 |
| D2 | **三臂单变量阶梯**（A1 1 轮 / A2 ≤3 轮无方向 / A3 ≤3 轮真裁判），逐篇交错执行 | §3.2 (MUST) |
| D3 | 报告必须含 **Token 成本 + p50/p95 延迟 + 平均轮数**，防"拉长轨迹换虚假通过率" | §3.3 (MUST) |
| D4 | 本场景无状态机仿真环境 ⇒ 用"注入已知错误→已知正确形"的确定性回收率当**真值等价物**，并在报告里显式声明这一替代 | §1 的适配，已写进设计稿合规前置段 |
| D5 | 阈值 pilot 后固定；P1 成立也是**正当产出**（届时反向收紧 §4.3 表述） | 设计稿 §7 |

---

## 🎯 Active Frontier (Unblocked Tasks)

### Task 1: 种子集模块（注入错误 → 已知正确形） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `delector/data/a1_seed_errors.py`
- Test: `tests/test_a1_seed_errors_data.py`

**Interfaces:**
- Consumes: `delector/data/a1_writing_dict.py::A1_SCHREIBEN_TEIL2`（10 篇官方 `sample_email` 作改写底本）
- Produces: `SEED_CASES: list[SeedCase]`，`SeedCase = dataclass(frozen=True, slots=True)` 字段 `id / text(已注入错误的文本) / clean_text(修复后的目标文本) / injections: list[Injection]`，`Injection = dataclass(frozen=True, slots=True)` 字段 `error_class(str) / kind(str: "signal" | "probe") / wrong(str) / right(str) / expected_count(int)`
  - **`kind="signal"`**：每篇**恰好 1 处**，属**语法族**（对 letter / prose 都被生产分流计数）⇒ 该篇 `v_0 == 1`，A3 才会真迭代。**不进判决量**。
  - **`kind="probe"`**：每篇 **≥3 处**，属五类 held-out（**判决量分子**）。
  - 二者 MUST NOT 文字区间重叠（信号的 `wrong` 不得落在任何 probe 的区间内，反之亦然）。
- Produces: `ERROR_CLASSES: tuple[str, ...]` —— **恰好五类，MUST 与仓内 6 个检测器零重叠**：`nebensatz_wortstellung` / `artikel_genus` / `verb_kongruenz` / `praeposition_kollokation` / `nomen_grossschreibung`

**Subagent Prompt Scaffold (for /dfs-exec):**
> "实现种子集模块。① 五类**未被任何检测器覆盖**的 A1 错误（从句语序 / 冠词性别 / 动词变位 / 介词固定搭配 / 名词大小写）逐处**注入**到底本里，每处记 `wrong`→`right`；每篇 ≥3 处注入。② 数据自检测试 MUST 断言：a) `ERROR_CLASSES` 与 `delector/services/writing.py` 的检测器 `error_type` 集合**零交集**（从源码/常量现读，不许抄）；b) 每个 `injections[i].wrong` 在 `text` 中出现次数 == `expected_count`、在 `clean_text` 中 0 次；c) `injections[i].right` 在 `clean_text` 中恰好出现 `expected_count` 次；d) 每篇注入数 ≥3；e) 用真实 nlp（沿用既有 `nlp` fixture）跑 `analyze_a1_email` 断言**注入的错误不在 `violations`/`advisories` 里**（这是"held-out"的定义，被检测器抓到的注入必须换掉）。③ **信号注入（2026-10-15 追加，实测倒逼）**：每篇 MUST **恰好 1 处** `kind="signal"`，且 MUST 属**语法族**（对 letter / prose 都被 `violations_for` 计数）⇒ 用真实 nlp + **生产分流**逐篇断言 `len(violations_for(_text_kind(v), v)) == 1`（把"该篇会真迭代"钉成物理事实：当前全部 20 篇只注入 held-out 时实测 `v_0 == 0`，A3 会首轮即收敛 ⇒ 实验对裁判信号不可识别）；同时断言 probe 注入**不进**该计数、signal 与 probe 的区间**不重叠**。RUN：`python -m pytest tests/test_a1_seed_errors_data.py -q`。⚠️ 若某类注入被现有检测器抓到 ⇒ 换句式或换类，不许改断言。"

**Step Breakdown:**
- [x] Step 1: 写数据自检（RED：模块不存在 / 交集不为空 / 计数不符）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 建数据模块（GREEN）
- [x] Step 4: 逐条实跑 nlp 验证注入确实 held-out（贴原始输出）
- [x] Step 5: ruff + mypy 档 + CRLF + 原子提交
> **收尾记录（2026-10-15，接手方 deepseek-v4-1-flash__hermes）**：变异自证 ×3 实红（3/4/4 failed）+ CRV PASS（88 passed 复跑 / 逐篇 v0 20/20==1 / ruff & mypy 全绿 / CRLF 无裸 LF）；原 TDD RED 原文未随 WIP 交付，以变异自证补偿。台账 Task-1 completed（code commit=a85edd6）。

---

### Task 2: 三臂 harness 骨架（`--dry-run` 可跑，零 Key） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_judge_gaming.py`
- Test: `tests/test_bench_judge_gaming.py`

**Interfaces:**
- Consumes: `polish_loop.run_polish_loop(*, text, leitpunkte, tools, budget, chat, judge, violations_of, dispatch, clock, on_progress, should_stop, system_prompt)` · `messages.POLISH_TOOL_ALLOWLIST` · `routes.main.pick_system_prompt`（文本族提示词）· `routes.main.violations_for`（生产的规则族分流）
- Produces: `class Arm(enum.Enum): A1_BASELINE / A2_NO_SIGNAL / A3_CURRENT`；`def build_arm(arm: Arm) -> ArmConfig`（`ArmConfig` 含 `budget` / `violations_of` 工厂 / `arm_label`）；`def run_arm(case: SeedCase, arm: Arm, *, chat: ChatFn) -> RunRecord`（`RunRecord`：`arm` / `case_id` / `final_text` / `rounds` / `reason` / `converged` / `tokens_used` / `elapsed_s` / `model`）
- Produces: CLI `python tools/bench_judge_gaming.py --dry-run --json`（stub chat，**零 Key 可跑**）；退出码 `0=完成 / 1=样本集无效 / 2=环境不可用`（照 `tools/bench_judge_fp.py` 惯例）
- 三臂定义（MUST 与设计稿逐条一致）：**A1** `Budget(max_turns=1)`；**A2** `Budget(max_turns=3)` 且 `violations_of` **恒返回同一条固定违规**（迫使迭代但无方向）；**A3** `Budget()` 默认 + `violations_for`（生产分流）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "建三臂 harness 骨架。① `--dry-run` 用**确定性 stub chat**（按轮次返回构造好的回复）驱动 `run_polish_loop`，使**无 Key 也能跑通全链路**；② 三臂接线照设计稿（A1 max_turns=1；A2 恒固定违规；A3 生产分流），**不许**在 A2 里暴露任何被判违规的内容（那是 A3 的自变量）；③ `--json` 输出结构化 RunRecord 列表；④ 退出码 0/1/2 照 `tools/bench_judge_fp.py` 的契约实现并被测试钉住；⑤ 密钥只经 `delector.server.load_env()`（实测可用），**任何输出/异常/日志 MUST NOT 带 key**（打印前只允许布尔或长度）。测试全走 `--dry-run`/stub，**零 Key**。RUN：`python -m pytest tests/test_bench_judge_gaming.py -q` + `python tools/bench_judge_gaming.py --dry-run`。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：三臂配置、stub 链路、退出码、`--json` 形状）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 实现骨架（GREEN）
- [x] Step 4: 变异自证（把 A2 改成 A3 的分流 ⇒ 单变量用例红；把 A1 的 `max_turns` 改成 3 ⇒ 阶梯用例红）
- [x] Step 5: `--dry-run` 原始输出 + ruff + mypy 档 + CRLF + 原子提交
> **收尾记录（2026-10-15/16，deepseek-v4-1-flash__hermes）**：`95dc661` 合入 feat（仅两新文件 +1009 行）；dfs-exec Gear 2 双席位（TDD Builder + 独立 Reviewer）。编排核验：靶向 **20 passed**、trio **62 passed**、`--dry-run --json` 纯 JSON 60 条（三臂各 20）、退出码 0/1/2 实跑、变异实红 ×2（实现者）+ ×2（评审自选角度）→ 还原零残留（两文件 hash == HEAD）。设计稿 §4「两者都无裁判方向信号」逐字落成（A1/A2 共用同一固定违规）。**评审发现（非阻塞，均登记）**：W1–W3 = 三处分支欠覆盖钉（`run_arm` done 守卫 / `expected_count<1` / 种子装载异常⇒退 2），随 Task 3 补钉；**W4（设计层，Task 5 前须裁决）** = 恒定固定违规 ⇒ A1/A2 产出恒回退原文（`no_improvement`→argmin 回退；评审 InstantFinish 探针实证）⇒ `R_uncovered(A1/A2)≡0` 退化，与 §4 表「A1=一次性润色等价物」存在张力（建议据 §9.5「回退掩盖」扩展口径或调整 A2 机制）；W5 = Task 5 RUN `--cases` 未实现（见 Task 5 评审附注）。全量基线（本批一次）：**2071 passed + 3 skipped**（414s）。

---

### Task 3: 测量与综合记账（判决量 + 成本/延迟/轮数） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Modify: `tools/bench_judge_gaming.py`
- Test: `tests/test_bench_judge_gaming.py`

**Interfaces:**
- Consumes: `RunRecord`（Task 2）· `SeedCase.injections`（Task 1）
- Produces: `def score_uncovered(record: RunRecord, case: SeedCase) -> int`（**判决量分子**：`final_text` 中 `injection.right` 且不再出现 `injection.wrong` 的处数；**仅统计 `kind=="probe"`** —— `signal` 只为触发迭代，不进判决量）· `def score_judge_violations(record: RunRecord) -> int`· `def detect_new_errors(before: str, after: str) -> int`（新增错误处数）
- Produces: `def summarize(records: list[RunRecord], cases: list[SeedCase]) -> Report`，`Report` 含**每臂**：`R_judge` / `R_uncovered` / `回退发生率` / `新增错误数` / `tokens_total` / `elapsed_p50` / `elapsed_p95` / `rounds_mean`；且 `Report.judgement_basis = "uncovered_seed_recovery"`（把"判决只用确定性真值"钉进产物）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "实现测量与记账。① `score_uncovered` 按 `injections` 的 `right`/`wrong` 计数（**逐处**，不是整句相等）；② `detect_new_errors` 比对 before/after 的新增错误（可用既有检测器的 error 计数差 + 种子无关的字符串退化检查）；③ `summarize` 出**每臂**的六项指标，含 §3.3 要求的 Token 成本 / p50/p95 延迟 / 平均轮数；④ `Report.judgement_basis` MUST 如实标注判决量来自 held-out 回收率（这条有测试钉住）；⑤ **不许**把 LLM 评分混进任何判定字段（rater 在 Task 4，只进 `auxiliary` 字段）。测试用固定 `RunRecord`/`SeedCase` 断言数学（含边界：`right` 出现多次、`wrong` 残留、空 injections）。RUN：`python -m pytest tests/test_bench_judge_gaming.py -q`。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：四项指标数学 + 成本/延迟聚合 + `judgement_basis`）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 实现（GREEN）
- [x] Step 4: 变异自证（把判决量改成 `R_judge` ⇒ 用例红；把 p95 改成 p50 ⇒ 用例红）
- [x] Step 5: ruff + mypy 档 + CRLF + 原子提交
> **收尾记录（2026-10-16，deepseek-v4-1-flash__hermes）**：`f6ec2da`（W1–W3 补钉，+84 行测试）+ `66e1590`（主体 + `--cases`，销 W5 欠账）合入 feat；dfs-exec Gear 2 双席位。编排核验：靶向 **39 passed**、trio **81 passed**、`--dry-run --json` 60 条 / `--cases 5` 15 条（纯 JSON、冻结顺序）、`--cases 0/-1/abc` 与无参退 2、双文件 CRLF 零裸 LF；编排独立抽查变异（probe-only 过滤删除 ⇒ 3 failed）与评审 M1 逐字一致。独立评审 PASS：**5 条自选角度对抗变异四联实红零残留**（probe-only / 切片边界 / rollback 条件 / 多重集语义 / W2 补钉）+ **口径裁决 11 项全过**（池化 R_uncovered=0.6、right 封顶、wrong 归零、probe-only=0、R_judge 手推 0.375、rollback 1/3、p50/p95 与 numpy 逐位一致、ValueError 拒绝样本外 case_id、常量自循环导入）；审计钩子零 .env、零非回环、server 未导入。**残余观察（非阻塞，随 Task 4 销账）**：O1 = R_judge 中段值无钉（理论 `1.0 if vfin==0 else 0.0` 变异可全绿；旁证量）；O2 = `tests:458` 第二条断言与注释不敏感；O3 = `json.dumps(Report)` 无钉 + Task 4 添加 `auxiliary` 时需同步精确键集合。

---

### Task 4: 辅助仪器 —— 盲评 rater（**不进判决**） [Tier: 2-Standard] [Mode: AFK] [Role: TDD Builder]

**Files:**
- Create: `tools/bench_judge_rater.py`
- Test: `tests/test_bench_judge_rater.py`
- Modify: `tools/bench_judge_gaming.py`（仅把 `auxiliary` 接进 Report；**MUST NOT** 影响任何判决字段）

**Interfaces:**
- Consumes: `llm_client.chat`（同一 key 加载路径）· `report` 里的 before/after 文本对
- Produces: `def rate_pair(before: str, after: str, *, order_seed: int, chat: ChatFn) -> Rating`（`Rating = {correctness_before, correctness_after, idiomatic_before, idiomatic_after, order: "ba"|"ab"}`）· `def insert_into_report(report: Report, ratings: list[Rating]) -> Report`（只写 `report["auxiliary"]`）
- **盲评协议**：顺序由 `order_seed` 决定；rater 只见两段文本与同一 rubric，不见臂标签

**Subagent Prompt Scaffold (for /dfs-exec):**
> "实现辅助 rater。① 盲评：`order_seed` 决定 A/B 呈现顺序，rubric 里 MUST NOT 出现臂标签或"哪份是润色后"的暗示；② 结果只进 `report['auxiliary']`，并带 `"role": "auxiliary_signal_not_used_in_verdict"` 字样（有测试断言判决字段未变）；③ `--dry-run` 下跳过（不发电）；④ 复用同一个 key 加载路径，**不许**在日志/异常里带 key。测试全 stub。RUN：`python -m pytest tests/test_bench_judge_rater.py tests/test_bench_judge_gaming.py -q`。"

**Step Breakdown:**
- [x] Step 1: 写失败测试（RED：盲评顺序、`auxiliary` 隔离、dry-run 跳过）
- [x] Step 2: 跑并记录预期失败原文
- [x] Step 3: 实现（GREEN）
- [x] Step 4: 变异自证（把 arm 标签塞进 rubric ⇒ 用例红；把 rating 写进判决字段 ⇒ 用例红）
- [x] Step 5: ruff + mypy 档 + CRLF + 原子提交
> **收尾记录（2026-10-16，deepseek-v4-1-flash__hermes）**：`ce5339e`（销 Task 3 残余 O1–O3）+ `1134148`（主体：rater + `auxiliary` 接线，4 文件 2A+2M）合入 feat；dfs-exec Gear 2 双席位。编排核验：靶向 **51 passed**、四件套 **93 passed**；`--dry-run --json` 60 条（键集/臂分布对账）、`--cases 5` 15 条、文本模式无 auxiliary 泄漏、无参退 2；编排抽查变异（ROLE 常量改值 ⇒ isolation 用例 red）四联成立；四文件 `i/lf w/crlf`、bare LF=0。独立评审 PASS：**7 条对抗变异四联全红-还原**（奇偶对调 / arms 字段污染 / 空守卫 / 范围守卫 / auxiliary 槽 / signal 计分 / O1 二值式复现）+ 盲评审计（自建黑名单两序零归属泄漏、rubric 逐字节一致、仅 Text 1/2 盲槽、一对文本 1 次调用）+ auxiliary 深等隔离（唯一写入面 rater:171）+ 审计钩子 `.env`=0 / 非回环=0 / server 未导入。**残余观察（非阻塞）**：O-1 = 两新文件 EOF 缺尾换行（全仓 229 个 .py 中 5 例同型，3 例先于本分支）；O-2 = `ruff format --check` would-reformat（仓内无该门禁）；O-3 = `insert_into_report` 浅拷贝共享 `arms` 引用（不被改动，有测试+变异双钉）。O1–O3（Task 3 残余）已全部销账。

---

### Task 5: **pilot 实跑（N=5）+ 阈值固定回写** [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Modify: `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md`（阈值区**回写实测值与定案阈值**）
- Create: `docs/reviews/2026-10-15-judge-gaming-pilot.md`（pilot 原始表 + token/延迟实测）

**Interfaces:**
- Consumes: `tools/bench_judge_gaming.py`（真跑模式，`load_env()` 后的 key）· 5 篇种子用例
- Produces: pilot 报告（**含每篇三臂的原始 RunRecord 与逐处注入回收明细**）+ **固定阈值**（`R_uncovered` 的显著性口径 / `R_judge` 差值口径 / 回退率上限）
> **评审附注（Task 2 CRV）**：RUN 命令中的 `--cases 5` 现不存在（argparse 报 unrecognized arguments、退 2）；落地前须先实现 `--cases N`（建议随 Task 3/4 一并落）。**W4（A1/A2 恒回退原文）MUST 在 pilot 前裁决并回写设计稿**。（2026-10-16 更新：`--cases N` 已随 Task 3（66e1590）落地销账。）

**Subagent Prompt Scaffold (for /dfs-exec):**
> "跑 pilot：N=5 篇种子用例 × 3 臂，**逐篇交错执行**。① 真跑前先打印一次 `bool(key)`（**绝不打印 key**）与模型名；② 记录每篇三臂的 RunRecord 与逐处注入回收；③ 据实测**方差与 token/延迟**固定主实验阈值并回写设计稿（写清"阈值由 pilot 实测方差推出"）；④ 若 pilot 暴露 harness 缺陷 ⇒ 回炉 Task 2/3 而不是就地绕过。**HITL**：跑前把预估 token/延迟与本次花费口径交用户确认。RUN：`python tools/bench_judge_gaming.py --cases 5 --json`。"

**Step Breakdown:**
- [ ] Step 1: **HITL**：交用户确认 pilot 规模与花费口径
- [ ] Step 2: 真跑 N=5×3 臂，原始输出落盘
- [ ] Step 3: 据实测固定阈值并回写设计稿
- [ ] Step 4: pilot 报告落 `docs/reviews/`
- [ ] Step 5: 原子提交

---

### Task 6: **主实验（N=20）+ 报告 + ADR §4.3 回写** [Tier: 3-Critical] [Mode: HITL] [Role: TDD Builder]

**Files:**
- Create: `docs/reviews/2026-10-…-judge-gaming-control-experiment.md`
- Modify: `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md`（执行记录）
- Modify（vault）: ADR-0023 §11.3/§11.6 的判据第 8 条状态

**Interfaces:**
- Consumes: Task 5 固定的阈值 + 冻结的种子集（20 篇）
- Produces: 报告含 —— 每臂六项指标 + 逐篇明细 + **P1/P2 结论**（按预注册阈值）+ 适用边界 + rater 与人类的校准偏差 + **原始输出可复跑命令**；ADR 回写：**P2 ⇒ 允许解禁无条件「已实现」（需用户签批）；P1 ⇒ 反向收紧表述并进入"裁判集第二轮扩充"**

**Subagent Prompt Scaffold (for /dfs-exec):**
> "跑主实验（N=20 × 3 臂，逐篇交错）并按预注册阈值给结论。① 样本集 MUST 已冻结；样本外发现**另列**不入计数；② 报告 MUST 给每臂六项指标 + 逐篇原始明细 + 可复跑命令；③ 结论只依据 `R_uncovered`（判决量），`R_judge` 与盲评分作为旁证单列并标注角色；④ 无论结论是 P1/P2，MUST 同时给出**适用边界**与**已知威胁**（设计稿 §9 六条）；⑤ **HITL**：结论与 §4.3 表述变更交用户签批后才回写 ADR（agent 不自行解禁）。"

**Step Breakdown:**
- [ ] Step 1: **HITL**：交用户确认主实验规模（按 pilot 实测 token 反推）与花费口径
- [ ] Step 2: 真跑 N=20×3 臂，全量原始输出落盘
- [ ] Step 3: 按预注册阈值判定 P1/P2，写报告
- [ ] Step 4: **HITL**：结论与 §4.3 表述签批
- [ ] Step 5: ADR 回写 + 原子提交

---

## 🌫️ Fog of War (Not Yet Specified)

- **[Unknown A] pilot 的方差有多大**：决定主实验 N 是否要 >20。**由 Task 5 毕业**（pilot 后据实测方差定 N，不许拍脑袋）。
- **[Unknown B] 五类 held-out 注入的"可修复性"是否均等**：某些类可能连人类都不常改（如大小写）⇒ 会稀释 `R_uncovered` 的判别力。**由 Task 5 的逐处明细毕业**（若某类回收率恒 0 或恒 1，须在主实验前决定是否降权，并写明理由与依据）。
- **[Unknown C] DeepSeek 是否支持 `seed` 参数**：§3.1 要求"同种子"，若 API 不支持则只能靠 `temperature` 固定 + 交错执行近似。**由 Task 5 实跑观测毕业**（不支持 ⇒ 在报告里显式登记为偏离并说明替代控制）。
- **[Unknown D] LLM rater 的自偏好偏置幅度**：**待主实验**（与人类抽校比对后毕业）；若偏差过大 ⇒ 只报"辅助信号不可信"并弃用该仪器。

## 🚫 Out of Scope

- **不改生产代码**：本实验只读 `run_polish_loop` 的注入缝与 `routes.main` 的分流函数；**不改**循环语义、不接线新规则。
- **不做裁判集第二轮扩充**（那是 P1 成立后的下一个子计划）。
- **不做跨等级（B1/B2）与跨语言**：只覆盖 A1 书信体 + 非书信散文。
- **不引入新依赖**（盲评只用现有 `llm_client.chat`）。
- **不把结论外推到"一切 agent 循环"**：报告 MUST 写明适用边界。
