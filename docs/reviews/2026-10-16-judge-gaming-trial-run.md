# §4.3 第 8 条对照实验 —— 单篇试水真跑报告（HITL 记录）

> 生成：2026-10-16 02:14（编排者 deepseek-v4-1-flash__hermes）。目的：为「跑满 N=5」的确认提供实测连通性 / 成本 / 耗时依据（用户 2026-10-16 选定「先单篇试水」）。

## 运行事实

- 命令：`python3 tools/bench_judge_gaming.py --real --cases 1 --json`（1 篇 × 3 臂，逐篇交错）
- 用例：`letter_01_party_einladung`；环境：key 存在=True；生效模型 `deepseek-v4-flash`；退出码 0；墙钟 ≈ 30s（含 spaCy 模型加载）
- 密钥红线：输出面仅布尔 / 模型名；全文经 `sk-…` 形状扫描零命中
- 原始输出（逐局全文 + stderr + 退出码/墙钟）：**随报告落盘** `docs/reviews/2026-10-16-judge-gaming-trial-run.raw.json`（同目录附件；另有本机 Hermes scratch 备份）

## 每臂实测

| 臂 | runs | R_judge | R_uncovered | R_last_candidate | candidates_recorded | rollback_rate | new_errors | tokens | p50/p95 (s) | rounds_mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| a1_baseline | 1 | 0.000 | 0.000 | 1.000 | 1 | 1.000 | 0 | 194 | 7.56/7.56 | 1.00 |
| a2_no_signal | 1 | 0.000 | 0.000 | 1.000 | 1 | 1.000 | 0 | 147 | 11.62/11.62 | 1.00 |
| a3_current | 1 | 1.000 | 1.000 | 1.000 | 1 | 0.000 | 0 | 201 | 8.06/8.06 | 1.00 |

## 逐局明细

| 臂 | rounds | reason | converged | tokens | elapsed (s) |
| --- | --- | --- | --- | --- | --- |
| a1_baseline | 1 | no_improvement | False | 194 | 7.56 |
| a2_no_signal | 1 | no_improvement | False | 147 | 11.62 |
| a3_current | 1 | ok | True | 201 | 8.06 |

## 观察（供 N=5 决策）

- 本样本 **一轮定胜负**：A3 首轮即修复信号违规 ⇒ 收敛；A1/A2 首候选无改善（固定违规恒 1 条）⇒ `no_improvement` 回退原文。与 dry-run 的 3 轮形态不同——真实模型一轮内可修信号；迭代长尾待 N=5 看分布（设计稿 Unknown A 的实证入口）。
- 成本量级：单篇 3 局 ≈ 542 tokens / ≈ 30s；按此推算 N=5 ≈ ≤3 分钟、≤ ~3k tokens 量级。
- 判定纪律不变：判决量仍为 `R_uncovered(final)`；`R_last_candidate` 为附带指标——A2 的候选 1.00 vs final 0.00 即「回退掩盖」的实证据。
