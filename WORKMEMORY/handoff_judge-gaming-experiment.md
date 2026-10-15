---
to: any
from: codebuddy (GLM-5.3-Flash)
created: 2026-10-15
role: IMPLEMENT | TEST | VERIFY
required_capability: python-3.11 / spaCy(de_core_news_sm) / 真实 DEEPSEEK_API_KEY（Task 5/6 才用）
status: open
---

# 交接包：§4.3 第 8 条对照实验（浅裁判是否真被模型针对）—— Task 1 已完成待验收，Task 2~6 待做

## 一、任务上下文（60 秒读完）

- **判据原文**（ADR-0023 §4.3）：「浅裁判 + 循环 = 奖励黑客：模型会学会『通过检查』而非『写得更好』」⇒ 实验必须能分别证伪 **P1（奖励黑客）/ P2（真变好）**。
- **计划正本**：`docs/plans/2026-10-15-judge-gaming-experiment.md`（6 任务，台账 **0/6，Task-1 IN_PROGRESS**）。
- **设计正本**：`docs/specs/2026-10-15-judge-gaming-control-experiment-design.md`（已按 `AGENT-EVALUATION-HARNESS` §1/§3 与 `AGENT-CONDUCT` §10.2 修正：**判决量只有一个 = held-out 种子错误的确定性回收率 `R_uncovered`**；LLM 盲评是**辅助信号、不进判决**；报告必须带 Token 成本 + p50/p95 延迟 + 平均轮数）。
- **用户已拍板（2026-10-15）**：
  1. 测**现状形态**：实测发现 `polish_loop` **不把裁判结论回灌模型**（`messages.append` 站点清单见设计稿"仪器 A"修订段），模型只能主动调 `writing_check` 自查 ⇒ 本实验测的就是这个形态；**「裁判结论回灌（verifier-in-the-loop）」登记为下一个子计划**（产品能力变更，不只为了实验）。
  2. 种子 = **每篇恰好 1 处「信号」注入**（语法族、被生产分流计数 ⇒ 该篇 `v_0 == 1`）+ **≥3 处 held-out 探针**（判决量分子）。**判决只算 probe，signal 只为触发迭代**。
  3. 盲评 rater = 辅助信号。
- **密钥**：`.env` 已配 `DEEPSEEK_API_KEY`（**已被 gitignore 且未跟踪** ✓）。harness 只经 `delector.server.load_env()` 载入（编排者实测：载入后 `os.environ` 与 `get_effective_api_key()` 均非空）。**MUST NOT 打印/落盘/提交 key** —— 输出与报告里只允许布尔或长度。

## 二、已完成（含证据）

- **Task 1 代码完成（⚠️ 待 CRV 验收 + 变异自证补证，见"风险"）**：`delector/data/a1_seed_errors.py` + `tests/test_a1_seed_errors_data.py`（**88 passed**）。接口：`SeedCase/Injection(含 kind: "signal"|"probe")` + `SEED_CASES`（**20 篇** = 10 官方书信范文反向注入 + 10 篇 `corpus_dict.OFFICIAL_CORPUS` 非书信课文逐字复制后注入）+ `ERROR_CLASSES`（恰好五类 held-out：nebensatz_wortstellung/artikel_genus/verb_kongruenz/praeposition_kollokation/nomen_grossschreibung）。
- **编排者已逐篇实测（物理证据，替代死亡 maker 的报告）**：20/20 篇 `sig=1 / probe≥3 / 生产分流 v0=1`（signal 的 rule 分布：kasus×9 / artikel×8 / praeposition×3）；ruff 全绿；`mypy --strict delector` 68 files 0；CRLF lone_LF=0。
- **测试断言三层**：接口层（五类名/20 篇/两类各≥10/frozen+slots）· 字符串层（wrong/right 计数复算 + **双向回放** text↔clean 差异恰好是注入）· held-out 层（真实 nlp 三重差分：rule 计数多重集相等 + span 不落 wrong 区间 + 逐处回退后仍相等）+ **信号层**（每篇恰 1 signal + 生产分流 v0==1 + probe 不进计数 + 区间不重叠）。检测器 `error_type` 集合**从源码现读**（≥6 下限防正则失效假绿）。
- **计划/设计稿的"信号注入"修订**已落盘（本包一起提交）。
- **沉淀已完成**（99-Inbox 两张）：① `2026-10-15-规则引擎硬门必须按「类」覆盖正样本…`（含两条既有规则的新证据实例：自动化接线三证 / UNVERIFIED 逐条核销）；② `2026-10-15-bash-standards-§5.3-缺的一条：嵌入的-ascii-双引号…`。

## 三、未完成与下一步（按序）

1. **⏳ Task 1 收尾**：a) **变异自证补证**（上轮 maker 死于报告前，未跑）：① 把某篇 signal 换成 held-out 类 ⇒ "信号真被计数"用例红；② 删某篇 signal ⇒ "恰好 1 处"红；③ 把某篇 probe 换成可计数错误 ⇒ held-out 用例红。b) **CRV 验收**（把上面的逐篇 v0 表 + 88 passed 作为证据带上）。c) 原子提交（两新文件 + 计划/设计稿修订一起）。
2. **⏳ Task 2**：三臂 harness 骨架（`tools/bench_judge_gaming.py` + 测试）—— A1 `max_turns=1`；A2 `max_turns=3` 且 `violations_of` 恒返回**同一条固定违规**（迫使迭代、无方向）；A3 = 生产分流。`--dry-run`（stub chat）零 Key 可跑；退出码 0/1/2 照 `tools/bench_judge_fp.py` 惯例。⚠️ 密钥只经 `load_env()`，任何输出不得带 key。
3. **⏳ Task 3**：测量与记账 —— `score_uncovered`（**只算 probe**）/ `score_judge_violations` / `detect_new_errors` / `summarize`（每臂 `R_judge`/`R_uncovered`/回退率/新增错误/Token/p50/p95/平均轮数）+ `Report.judgement_basis="uncovered_seed_recovery"`（钉"判决只用确定性真值"）。
4. **⏳ Task 4**：盲评 rater（`tools/bench_judge_rater.py`）—— 顺序由 `order_seed` 决定、rubric 无臂标签、结果只进 `report["auxiliary"]`（有测试断言判决字段未变）；`--dry-run` 跳过。
5. **⏳ Task 5（HITL）**：pilot N=5 真跑（先交用户确认花费口径）→ 按实测方差**固定阈值回写设计稿**。
6. **⏳ Task 6（HITL）**：主实验 N=20 真跑 → 报告落 `docs/reviews/` → **结论交用户签批后**才回写 ADR §4.3（P2 ⇒ 才可解禁无条件「已实现」；P1 ⇒ 反向收紧）。

## 四、风险与坑（都实测过）

1. **子代理派单不稳**：本会话中断 **6 次**（10003×2 / 10006×3 / 10101 / 6004）。6004 那次死前落盘且状态完好（本包已核）。**给 maker 的 prompt MUST 带反挂死纪律**（所有 sleep 有 `wait_for`/固定次数兜底、禁 join、禁无界 while、单用例 <5s、连续两次跑不完就停手报告）。
2. **提交信息禁 inline `-m`**（中文 + 引号/反引号会截断或静默缺字）—— 一律 `git commit -F <file>`，消息文件用 `python - <<'PYEOF'`（**定界符带引号**）生成；详见 99-Inbox 那张 BASH 草稿。
3. **判决量纪律**：`score_uncovered` 只算 `kind=="probe"`；signal 绝不进判决（它只是"点火器"）。LLM rater 只进 `auxiliary`（`AGENT-EVALUATION-HARNESS` §1 + `AGENT-CONDUCT` §10.2 两条 MUST）。
4. **生产分流下散文的 `a1_greeting_missing` 不计数**（格式族被 prose 过滤）—— 上一个 maker 曾用 `collect_violations` 口径误报 v0=1，**必须用 `routes.main.violations_for + _text_kind` 口径**。
5. **既有网络型 flaky**：`tests/test_server.py::test_get_audio_tts_returns_mp3` 走 Edge TTS（单跑绿、批跑偶发 500）—— 与本实验无关，别追。
6. **预注册纪律**：阈值 pilot 后固定回写设计稿；样本冻结；剔除文本唯一正当理由是"文本本身构造错误"且须写明；**P1 成立也是正当产出**（届时 §4.3 表述反向收紧）。

---
## 响应（2026-10-15 23:17 | deepseek-v4-1-flash__hermes）—— 已接手；Task 1 收尾完成（CRV PASS）；Task 2~6 仍待做（**status 保持 open**）

读包 → 独立复核（全实跑）→ 补跑变异自证 ×3 → Task 1 结清；台账 Task-1 → completed。

### 1. 独立复核（非转述；复现命令内嵌，原始输出存本机 scratch）
- `python3 -m pytest tests/test_a1_seed_errors_data.py -q` ⇒ **88 passed in 4.40s**（每条变异还原后再跑：88 passed in 4.82s）。
- 逐篇 v0 表重跑（`-s` 打印为测试内置）：**20/20 `v0==1`**，被计数条 `rule` == signal.error_class，probe 3~5 处/篇。
- `ruff check .` 全绿；`mypy --strict delector` **68 files 0**；两新文件 CRLF、lone_LF=0。
- **勘误 1 条**：signal 的 rule 分布实测为 **kasus×9 / artikel×9 / praeposition×2**（a85edd6 提交消息与包内 §二 写 9/8/3，系笔误；无功能影响，以物理重算为准）。

### 2. 变异自证 ×3（补证；逐条「注入缺陷 ⇒ 守卫实红」，跑后 `git checkout --` 还原、零残留）
- **① L1 signal 换 held-out 类**（`kasus` → `nomen_grossschreibung`；`zu der Hause`→`zu hause`）⇒ **3 failed / 85 passed**：
  - `test_signal_is_counted_as_exactly_one_violation_under_production_routing[letter_01]`〔v_0 应为 1，实际 0（rules=[]）〕 ← **目标用例实红**
  - `test_probe_injections_are_held_out_from_detectors[letter_01]`〔text 计数 != clean + signal 一条〕
  - `test_every_case_has_exactly_one_signal`〔signal 不得取 held-out 类名〕
- **② 删 L2 signal**（`mein Termin` 行）⇒ **4 failed / 84 passed**：
  - `test_every_case_has_exactly_one_signal`〔signal 数 0 != 1〕 ← **目标用例实红**
  - ranges / held-out / v0 三处 signal 依赖用例（均报「应有恰好 1 处 signal，实际 0」）
- **③ L6 nomen probe 换可计数错误**（`am freitag`→`für dem Freitag`）⇒ **4 failed / 84 passed**：
  - `test_probe_injections_are_held_out_from_detectors[letter_06]`〔text 计数 != clean + signal 一条（{praeposition:1, kasus:1} vs {kasus:1}）〕 ← **目标用例实红**
  - `test_signal_is_counted...[letter_06]`〔v_0 应为 1，实际 2（rules=['praeposition','kasus']）〕
  - `test_all_five_classes_actually_used_in_probes`〔unknown=['kasus']〕+ `test_string_level_consistency[letter_06]`（替换次序连带效应——防御纵深的两道额外防线）
- **复跑指引**：三条变异均为对 `delector/data/a1_seed_errors.py` 的单行字符串替换（锚点 = 各自 `Injection(...)` 整行）；复核者按上述括号内改写、跑全测试文件、`git checkout --` 还原即可逐字复现。

### 3. 簿记
- 原子提交判定：Task 1 代码 + 测试 + 计划/设计稿修订**已在 `a85edd6` 一次性落地**（包内「三、1(c)」条件达成；WIP 仅为措辞）。本次补交收尾簿记（计划五步勾选 + INDEX + 本响应节）与 work.log 事件——**收尾簿记提交 hash 见 work.log 同日「NOTE」条目**。
- 台账 `.vault-exec-ledger.json` Task-1 → completed（**本仓 gitignore 的本地文件，不入库**；commit_hash=a85edd6）。
- 原 TDD RED 原文未随 WIP 交付（maker 会话被 6004 掐断于报告前）⇒ 以变异自证 ×3 补偿「测试非真空、守卫真能红」这一证明义务；RED 阶段原始输出无法事后补录，如实登记为**已观测缺口（不阻塞）**。
- **本收尾在独立 worktree（`.worktrees/judge-gaming-closure`）完成**——主目录曾于 2026-10-15 23:11:36 被并行操作切至 `chore/swarm-audit-master`（不干扰该线；事故与处置详见 work.log 同日第三条 NOTE）。

### 4. 下一步（按原包「三」清单，不变）
Task 2（三臂 harness 骨架，AFK、`--dry-run` 零 Key 可跑）→ Task 3/4 → Task 5/6（HITL：真跑前交用户确认花费口径）。**本会话范围声明**：仅接手 + Task 1 收尾；不改生产代码路径。

---

## 响应 2（2026-10-15 23:54 | deepseek-v4-1-flash__hermes）—— Task 2 交付（CRV PASS）；Task 3~6 待做（**status 保持 open**）

dfs-exec Gear 2 双席位交付 `95dc661`（`tools/bench_judge_gaming.py` 562 行 + `tests/test_bench_judge_gaming.py` 447 行；仅此两新文件，未触任何既有文件；已 ff 合入 feat）。

### 1. 编排水位核验（物理回执；原始输出存本机 scratch）
- 靶向复跑 **20 passed**（5.86s）；trio（+`test_ai_polish_loop`+`test_polish_tools`）**62 passed**。
- `--dry-run --json` 纯 JSON **60 条**（a1/a2/a3 各 20；a1 rounds=1 turn_limit；a2 rounds=3 no_improvement；a3 converged=20）；退出码 0/1/2 实跑（含无 `--dry-run` ⇒ 2 + 人话提示）。
- 设计稿 §4「A1→A2 两者都无裁判方向信号」逐字落成：A1 与 A2 共用同一固定违规函数（单变量严格；评审独立复核确认这是该条唯一严格读法）。
- 全量基线（本批一次）：**2071 passed + 3 skipped**（414s，feat@3207dba worktree 内）。

### 2. 独立评审（PASS）与欠账
- 4 条对抗变异（含 2 条评审自选角度：validate signal 检查 / A2 泄漏方向）实红 → `git checkout --` 还原 → 文件 hash == HEAD；审计钩子证零 .env、零出网（60 次 socket 全回环 = asyncio self-pipe）。
- **W1–W3**（非阻塞）：done 守卫 / `expected_count<1` / 种子装载异常⇒退 2 三处分支无覆盖钉 → **随 Task 3 补钉**。
- **W4（设计层，Task 5 前须裁决）**：恒定固定违规 ⇒ A1/A2 真跑产出**恒回退原文**（评审 InstantFinish 探针实证）⇒ `R_uncovered(A1/A2)≡0`，「A2 关键分辨器」在输出面退化；与 §4 表「A1=一次性润色等价物」描述有张力。建议据 §9.5「回退掩盖」扩展口径，或调整 A2 机制后再进 pilot。
- **W5**：Task 5 RUN 的 `--cases` 未实现（计划已加评审附注）。

### 3. 下一步
Task 3（测量与记账 + W1–W3 补钉）→ Task 4（rater）→ Task 5/6（HITL：先交用户确认花费口径 + **W4 裁决**）。本会话范围：Task 2 交付；至此台账 2/6。

---

## 响应 3（2026-10-16 00:27 | deepseek-v4-1-flash__hermes）—— Task 3 交付（CRV PASS）；Task 4~6 待做（**status 保持 open**）

双提交落地：`f6ec2da`（Task 2 评审 W1–W3 覆盖钉，+84 行测试）+ `66e1590`（测量与综合记账 + `--cases`，销 W5 欠账）；已 ff 合入 feat。

### 1. 编排水位核验（物理回执）
- 靶向 **39 passed** / trio **81 passed**（编排与评审双复跑一致）。
- CLI：`--dry-run --json` 60 条纯 JSON（形状未动）；`--cases 5 --dry-run --json` 15 条（冻结顺序逐条核实）；`--cases 0/-1/abc` 与无参均退 2；文本模式含【综合记账】块。
- 编排独立抽查变异（probe-only 过滤删除）⇒ **3 failed**，与评审 M1 逐字一致；还原后 39 passed 零残留。

### 2. 独立评审（PASS）
- **5 条自选角度变异**四联实红零残留（probe-only / `--cases` 切片 / rollback 条件 / 多重集语义 / W2 补钉）。
- **口径裁决 11 项**对设计稿 §3/§4 全过（含池化 R_uncovered=0.6 手推、right 封顶、wrong 归零、probe-only=0、R_judge 手推 0.375、rollback 1/3、p50/p95 与 numpy 逐位一致、`ValueError` 拒绝样本外 case_id、`REASON_NO_IMPROVEMENT` 自循环导入）。
- 审计钩子：零 .env、零非回环出网、server 未导入。
- **残余观察 O1–O3（非阻塞）**：R_judge 中段值无钉 / `tests:458` 断言强度与注释不匹配 / `json.dumps(Report)` 无钉且 Task 4 需同步精确键集合 —— 已登记，**随 Task 4 销账**。

### 3. 下一步
Task 4（rater + `auxiliary` 接线 + O1–O3 销账）→ Task 5/6（HITL：先交用户确认花费口径 + **W4 裁决**）。台账：Task-3 完成（3/6）。
