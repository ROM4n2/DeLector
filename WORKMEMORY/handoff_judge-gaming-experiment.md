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
