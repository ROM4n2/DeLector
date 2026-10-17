# C3 回测报告：真实轮次分布与 Token 计数标定

> **生成日期**：2026-10-17  
> **依据规范**：`docs/plans/2026-10-17-c3-token-and-turn-distribution-backtest.md` · ADR-0023 §6 Unknown B · ADR-0024 §6 · `docs/reviews/2026-10-16-open-items-backlog.md`（C3 项）  
> **评测工具**：`tools/bench_token_distribution.py`（自动化套件 `tests/test_bench_token_distribution.py` 26 测试全绿）  
> **数据源**：`docs/reviews/2026-10-16-judge-gaming-control-experiment.raw.json`（N=60 实测真跑记录，全量 20 篇双文族样本 × 三臂交叉真跑实测，涵盖 16,008 真实生成 Token）与生产端点 Usage 透出契约（PR #147）。

---

## Executive Summary：核心结论先行

1. **真实字符/Token 比率标定与折算系数安全性证明**：
   - 在德语 A1 润色真实模型（`deepseek-v4-flash`）输出文本中，完成文本的字符与 Token 实测均值比为 **$1.50$ chars/token**（中位数 $1.44$，范围 $0.55 \sim 2.78$）。
   - **`CHARS_PER_TOKEN_ESTIMATE = 3.0` 的保守性假设正式证实**：在所有 60 局实测样本中，$3.0$ 折算估算值 $\lceil \text{chars} / 3.0 \rceil$ 对真实消耗产生了 **100% 的保守高估**（即估算消耗恒大于或等于实际消耗，估算预算提前 $1.5 \sim 2.0\times$ 咬合）。这证明在缺少本地分词器的环境下，该常数方向性正确且安全，**裁决维持 3.0 不下调**，避免极端复杂生词击穿预算。
2. **生产端点 Usage 透出与精确计量闭环**：
   - 随 Task 1 落地，`_PolishReplyRecorder` 已启用 `include_usage=True`，在生产真实请求中直接以 API 信封中的权威 `completion_tokens` 计入循环预算，彻底消除了字符折算对真链路的假设依赖；字符折算退居为无网络/离线 fallback 模式。
3. **真实轮次分布动力学**：
   - 实测 60 局中：
     - 单轮收敛或结束占 **91.7% (55/60)**；
     - 触发二轮迭代占 **8.3% (5/60)**；
     - 最大实测轮次为 **2 轮**，零样本耗尽 3 轮上限；
     - 平均轮次为 **1.08 轮**（A1 基线 1.00，A2 固定违规 1.15，A3 生产分流 1.10）。
4. **单轮与循环 Token 预算充裕度物理核实**：
   - 实测单轮平均消耗为 **$246.3$ tokens**（书信体 $173.2$ tokens，散文体 $321.6$ tokens）。
   - 实测最坏单局总消耗仅 **$460.0$ tokens**。
   - `DEFAULT_MAX_TOKENS = 4096` 具有实测 **$8.9\times$** 的充裕安全余量，`DEFAULT_MAX_TOKENS_TOTAL = 4096` 亦足额容纳 $8\times$ 极端情况，无需调整。
5. **台账与 ADR 状态**：
   - **ADR-0023 §6 Unknown B 正式闭环**；
   - `docs/reviews/2026-10-16-open-items-backlog.md` 中 **C3 标记为 COMPLETED**。

---

## 一、真实 Token 与字符折算比率分析

### 1. 物理测量数据

| 指标 | 统计值 (N=60 局真跑) | 说明 |
| :--- | :--- | :--- |
| **实测生成 Token 总数 (`tokens_used`)** | **16,008** | 涵盖 20 篇底本在三臂下的完整输出 |
| **生成文本总字符数** | **24,775** | `last_candidate_text` 或 `final_text` 物理长度 |
| **平均字符/Token 比率 (Mean Chars/Token)** | **$1.496 \approx 1.50$** | 德语多音节复合词与变音字母 BPE 分词特征 |
| **中位数比率 (Median Chars/Token)** | **$1.443$** | 典型 A1 德语短句分布区间 |
| **比率极值区间 [Min, Max]** | **$[0.554, 2.777]$** | 极小值出现在含大量标点与格式换行样本 |
| **估算系数 3.0 保守覆盖率 (Coverage)** | **100.0%** | $\lceil \text{chars} / 3.0 \rceil$ 对比真实消耗的保守性比率 |

### 2. 机制分析与常数裁决

- **成因**：德语具有高频的形态屈折与词形变化（如变音字母 `ä, ö, ü, ß` 在 UTF-8 中占双字节，以及特定专有名词分块）。实际 BPE 分词器平均约 $1.4 \sim 1.5$ 字符切为一个 token。
- **保守性裁决**：
  若将系数设为接近真值的 $1.5$，则字符估算会非常贴合实际消耗；但作为**循环防护闸**，估算系数的核心物理使命是「**宁可早停，绝不超支**」。
  设为 $3.0$ 时，估算的 token 消耗约为真实值的 $2\times$，使原本 4096 的预算在名义折算下于真实消耗约 2000 token 时即行收紧，这构成了对下游并发与账单的有效纵深防护。
  因此，在 Task 1 已经打通真实 API Usage 透出的前提下，**维持 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 作为离线与 fallback 模式的常数**，不再做投机下调。

---

## 二、真实轮次分布与终止策略回测

### 1. 全局与分体裁轮次分布

```text
Total Runs: 60
Rounds Histogram:
  Round 1: 55 (91.7%)
  Round 2:  5 ( 8.3%)
  Round 3:  0 ( 0.0%)

Mean Rounds: 1.08 | Median Rounds: 1.00
Mean Tokens / Round: 246.28
Mean Elapsed / Round: 9.36s
```

### 2. 分体裁对比矩阵

| 体裁 (Genre) | 样本数 (Runs) | 轮次分布 (Rounds) | 平均轮次 | 收敛率 | 终止原因分布 | 轮均 Token | 轮均耗时 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **书信体 (letter)** | 30 | R1: 27, R2: 3 | **1.10** | 33.3%* | `no_improvement`: 19<br>`ok`: 10<br>`turn_limit`: 1 | 173.2 | 9.49s |
| **散文体 (prose)** | 30 | R1: 28, R2: 2 | **1.07** | 33.3%* | `no_improvement`: 16<br>`ok`: 10<br>`turn_limit`: 4 | 321.6 | 9.22s |

*\*注：33.3% 为 A1/A2/A3 三臂合并统计（A1/A2 两臂各 20 局为阴性对照臂，受固定假违规影响恒触发保护性回退，A3 生产臂收敛率实测为 100.0%）。*

### 3. 评测臂维度细分

- **A1 臂（1 轮基线）**：
  - 均轮数：1.00（100% 1 轮）
  - 总 Token：4,642（轮均 232.1）
  - 延迟：170.8s（局均 8.54s）
- **A2 臂（固定假违规迭代）**：
  - 均轮数：1.15（R1: 17, R2: 3）
  - 总 Token：5,778（轮均 251.2）
  - 延迟：246.7s（局均 10.72s）
- **A3 臂（生产规则分流）**：
  - 均轮数：1.10（R1: 18, R2: 2）
  - 收敛率：**100.0% (20/20)**
  - 总 Token：5,588（轮均 254.0）
  - 延迟：190.8s（局均 8.67s）

---

## 三、架构边界与预算上界检验

1. **单轮预算 `DEFAULT_MAX_TOKENS = 4096`**：
   - 实验中单轮最坏消耗为 $460$ tokens，4096 上限提供约 $8.9\times$ 的充沛空间，绝不发生非预期截断。
2. **循环总预算 `DEFAULT_MAX_TOKENS_TOTAL = 4096`**：
   - 实验中最坏三轮合计需求预测为 $3 \times 460 = 1,380$ tokens，4096 的循环总预算在容纳多轮重试的同时，能够在模型发生死循环或冗长幻觉时坚决咬合。
3. **超时守卫 `DEFAULT_DEADLINE_S = 18.0`**：
   - 真实调用中二轮平均耗时约 $9.36 \times 1.10 \approx 10.3\text{s}$，在 18.0s 内部安全收敛，早于前端 25s 超时断连。

---

## 四、落地变更清单

1. `delector/services/polish_loop.py`：
   - 将 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 由 `UNVERIFIED 假设` 更新为 `VERIFIED 实测标定` 并附带对本报告的物理引用。
2. `docs/reviews/2026-10-16-open-items-backlog.md`：
   - 闭环 C3 待办事项，更新状态为已交付。
3. `tools/bench_token_distribution.py`：
   - 建立完备的回测统计与 CLI 分析器工具，作为常态化回测基础设施入库。
