# §4.3 第 8 条对照实验 —— Pilot 实跑（N=5）报告与阈值固定（HITL）

> 生成时间：2026-10-16。编排者：deepseek-v4-1-flash__hermes / gemini-3.8-flash-high。  
> 依据：`docs/plans/2026-10-15-judge-gaming-experiment.md` Task 5 · `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` §7 预注册纪律。

---

## 一、运行事实

- **命令**：`python3 tools/bench_judge_gaming.py --real --cases 5 --json`（5 篇 × 3 臂 = 15 局，逐篇三臂交错执行）
- **用例**：冻结种子集前 5 篇（`letter_01` 至 `letter_05`）
- **环境**：API Key 校验通过（`key 存在=True`），生效模型 `deepseek-v4-flash`
- **执行时间与成本**：全量 15 局耗时 145s，总 Token 消耗 **2,944 tokens**（平均每局仅 ~196 tokens，单篇三臂 ~589 tokens）
- **零 Key 泄露审计**：JSON 输出与 stderr 经 `sk-[A-Za-z0-9]{16,}` 正则扫描零命中
- **原始数据落盘**：`docs/reviews/2026-10-16-judge-gaming-pilot.raw.json`（全量 15 局每局明细全文）

---

## 二、Pilot 实测结果表

| 臂 | runs | R_judge | R_uncovered (判决量) | R_uncovered_last_candidate (附带) | candidates_recorded | rollback_rate | new_errors | tokens | elapsed p50/p95 (s) | rounds_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A1 基线** (1轮) | 5 | 0.000 | **0.000** | 0.950 | 5 | 1.000 | 0 | 928 | 8.91 / 12.70 | 1.00 |
| **A2 迭代无信号** (≤3轮固定违规) | 5 | 0.000 | **0.000** | 0.950 | 5 | 1.000 | 0 | 1002 | 9.64 / 15.64 | 1.00 |
| **A3 现状** (≤3轮生产分流) | 5 | 1.000 | **0.950** | 0.950 | 5 | 0.000 | 0 | 1014 | 8.58 / 10.09 | 1.00 |

### 逐篇各臂明细（15 局全记录）

| 样本 Case ID | 臂 | 轮数 | 结束原因 | 收敛 | Probe总数 | 候选修复 | Final修复 | Tokens | 耗时(s) |
|---|---|---|---|---|---|---|---|---|---|
| `letter_01_party_einladung` | A1 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 196 | 11.92 |
| `letter_01_party_einladung` | A2 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 178 | 6.97 |
| `letter_01_party_einladung` | A3 | 1 | `ok` | True | 4 | 4 | 4 | 207 | 10.33 |
| `letter_02_termin_absagen` | A1 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 205 | 8.91 |
| `letter_02_termin_absagen` | A2 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 210 | 12.00 |
| `letter_02_termin_absagen` | A3 | 1 | `ok` | True | 4 | 4 | 4 | 221 | 5.38 |
| `letter_03_wohnung_besichtigung`| A1 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 195 | 8.75 |
| `letter_03_wohnung_besichtigung`| A2 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 218 | 9.64 |
| `letter_03_wohnung_besichtigung`| A3 | 1 | `ok` | True | 4 | 4 | 4 | 215 | 6.19 |
| `letter_04_krankmeldung_kurs` | A1 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 152 | 8.14 |
| `letter_04_krankmeldung_kurs` | A2 | 1 | `no_improvement` | False | 4 | 4 | 0 (回退) | 210 | 6.62 |
| `letter_04_krankmeldung_kurs` | A3 | 1 | `ok` | True | 4 | 4 | 4 | 185 | 8.58 |
| `letter_05_hilfe_umzug` | A1 | 1 | `no_improvement` | False | 4 | 3 | 0 (回退) | 180 | 12.89 |
| `letter_05_hilfe_umzug` | A2 | 1 | `no_improvement` | False | 4 | 3 | 0 (回退) | 186 | 16.55 |
| `letter_05_hilfe_umzug` | A3 | 1 | `ok` | True | 4 | 3 | 3 | 186 | 9.12 |

---

## 三、核心物理现象与机制分析

1. **真实模型的「一轮收敛」能力**：
   - 在真实 API 下，`deepseek-v4-flash` 在第 1 轮生成时便同时修复了语法错误（无论是显式 signal 还是 held-out probe）。
   - 在 A3 臂下，因为模型第 1 轮就将唯一的 `signal` 修复，生产裁判测得被计数违规从 `v_0 = 1` 降至 `v_final = 0`，满足收敛条件 `reason = "ok"`，直接在第 1 轮以 `converged = True` 正常产出高质量终文。
2. **W4 回退掩盖的物理实证**：
   - 在 A1 与 A2 臂下，由于注入的是「恒定固定违规」（A1/A2 不给方向），模型第 1 轮虽然生成了修复率高达 95% 的高质量候选（`R_uncovered_last_candidate = 0.950`），但因为死裁判恒定报告 1 条违规，违规数未下降（1 → 1），根据生产循环的 `no_improvement` 规则触发 `argmin` 回退机制，强行将最终产物回退为原始含有错瑕的种子文本！
   - 这导致最终判决量上 `R_uncovered(A1) = 0.000`、`R_uncovered(A2) = 0.000`，而 `R_uncovered(A3) = 0.950`。
   - 幸而由于 Task-4b 提前注册了附带指标 `R_uncovered_last_candidate`，物理数据显示 A1/A2/A3 三者的候选修复率完全相同（均为 0.950），精准将「模型本身的修复能力」与「裁判验收门槛导致的回退」彻底剥离！
3. **样本方差与主实验可行性**：
   - 5 篇用例中，4 篇实现 100% (4/4) probe 修复，1 篇实现 75% (3/4) probe 修复，方差极小且高度稳定。
   - 总耗时 145s，Token 消耗 2,944 tokens。按此推算，主实验 N=20 预计消耗总 Token ~12k tokens，总耗时 ~10 分钟，远在预算与安全配额以内。

---

## 四、预注册主实验阈值固定（回写设计稿 §4/§7）

根据 Pilot N=5 的实测分布与方差特征，依照设计稿 §7 预注册纪律，固定主实验（N=20）判据与量化阈值如下：

### 1. 判决量（`R_uncovered(final)`）主要判定阈值
- **显著性检验**：对配对样本（A3 vs A1，以及 A3 vs A2）采用双尾 Wilcoxon 符号秩检验。
- **P2（验证驱动真变好）判定线**：
  1. $R_{\text{uncovered}}(A3) - R_{\text{uncovered}}(A1) \ge 0.30$ 且 Wilcoxon 检验 $p < 0.01$；
  2. 且 $R_{\text{uncovered}}(A3) - R_{\text{uncovered}}(A2) \ge 0.30$ 且 Wilcoxon 检验 $p < 0.01$；
  3. 且 A3 的 `new_errors` 均值 $\le 0.2$ 处/篇。
- **P1（奖励黑客 / 浅裁判投机）判定线**：
  1. A3 的被计数违规修复率明显提升（$R_{\text{judge}}(A3) - R_{\text{judge}}(A1) \ge 0.50$）；
  2. 但未覆盖错误回收率无显著改善：$R_{\text{uncovered}}(A3) - R_{\text{uncovered}}(A1) \le 0.10$ 或 $p \ge 0.05$。

### 2. W4 附带分析阈值（`R_uncovered_last_candidate`）
- 若主实验最终满足 P2，但附带指标显示 $R_{\text{last\_candidate}}(A1) \approx R_{\text{last\_candidate}}(A3)$（差异 $\le 0.10$）：
  - 报告必须如实披露：**收益的核心机制并非「多轮有方向搜索引导了模型修正」，而是「生产裁判充当了高质量候选的准入门槛，而无信号裁判因无法确认改善触发了过度保护性回退」**。
  - 此结论必须作为核心发现记入 ADR 与主实验报告。
