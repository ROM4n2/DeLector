# ADR-0031: Python import 迁移——削减启动期重依赖，同时保住红线 1 判定

- **状态**：Deprecated（方案 A 经双指标实测判负；判负数字与后续方向见 ADR-0032 §3.1）
- **日期**：2026-11-09
- **决策者**：席皓宇 (Haoyu Xi)
- **关联 ADR**：
  - 0018-performance-measurement-before-runtime-swap（先测量，再换运行时；本 ADR 沿用其「先量后改」口径）
  - 0027-nlp-model-sm-only（模型档位固定 `de_core_news_sm`，本 ADR 不改档位）
  - 0028-android-main-path-spacy-lazy-load（惰性加载先例；§5 引用其**反面**数字）
- **关联调研**：
  - `docs/research/2026-11-09-first-screen-startup-industry-research.md`（1.2s import 的分段归因）
  - `docs/research/2026-11-09-android-webview-prestartup-negative-result.md`（同环境基线 4016ms；并行化≠削减的实测）
- **关联代码**：`delector/nlp_engine/model_loader.py:20-25`、`delector/nlp_engine/processor.py:61-70`、`processor.py:416-419`

---

## 1. 背景与问题陈述

Android 冷启 TTFD（首条 `.article-row` 完成首次绘制）在 #319 之后为 **≈4016ms**
（x86_64 模拟器，同口径两轮中位数）。其中**监听前置**约 **1.2s** 花在三个重依赖的
Python import 上：

| 组成 | 说明 |
| --- | --- |
| `fastapi` | HTTP 框架，监听必需，无法移出前置段 |
| `delector.core.database` | 数据层初始化（含 `init_db()` 的预置数据 seed） |
| `import spacy` | 库导入本身约 1.09s（ADR-0020 §「冷启动 2.0s 未达」已记录），不含模型加载 |

> 来源：`docs/research/2026-11-09-first-screen-startup-industry-research.md` §「banner →
> NLP engine 行 = 1235ms」。该数字为 x86_64 模拟器口径，未覆盖真机。

### 1.1 现状的判定点

`model_loader.py:20-25` 在**模块导入期**尝试 `import spacy`，失败置 `spacy = None`；
`processor.py:61-70` 随即用这个结果一次性定死引擎分支：

```python
if spacy is None:
    # 红线 1：spaCy 缺失 ⇒ 纯 Python 降级路径（既有语义，保持不变）。
    nlp: Any = None
else:
    nlp = _LazyNlp()
```

`process_german_text()`（`processor.py:416-419`）只判断 `nlp is None`。也就是说：
**「spaCy 是否缺失」由导入期副作用决定**，而不是由一次显式的、可重试的探测决定。

### 1.2 红线 1 的既有语义

- spaCy 缺失 ⇒ 静默走纯 Python 降级（不崩溃、不联网下载、不冒充 spaCy 结果）。
- 该降级必须是**确定的终态**，不能出现「先假装可用、首次分析再失败」。
- 失败可见性、端口文件唯一真相、marker 校验、冷启动无空白页等其它不变量不受本 ADR 影响。

### 1.3 为什么不能靠「并行」解决

1.2s 是**进程内 import**，受 GIL 与 import lock 约束：起线程只能把它与别的等待窗口重叠，
不能减少 CPU 总量。2026-11-09 的 `startUpWebView` 负结果已经证明：把同类初始化挪到
后台线程与 Python 启动并行，会因为争同一份 CPU 而收益归零。

---

## 2. 决策驱动与验收口径（先于方案）

**双指标，缺一不可：**

| 指标 | 口径 | 作用 |
| --- | --- | --- |
| TTFD | 首条 `.article-row` 首次绘制；x86_64 模拟器，force-stop + `pm clear`（清 WebView/SW），每构建 7 次 × 2 轮，只认中位数 | 启动收益 |
| 首次分析耗时 | 冷启后**第一次**触发分析（首次点词 / 首次 `/api/analyze`）到结果可用的端到端中位数，同会话同环境 | 防止把成本搬家 |

**判定（实施 PR 必须照此报告）：**

- **合格**：TTFD 中位数 ≤ 基线 −5%（当前基线 4016ms ⇒ ≤ **3816ms**），**且**首次分析
  中位数 ≤ 基线 +100ms（噪声带内）。
- **不合格（明确判负）**：TTFD 改善 <100ms（<2.5%），或首次分析退化 >200ms（>5%），
  或任一轮首次分析 > 基线 +500ms。
- 双指标任一不达标即放弃，**不允许用另一个指标的改善抵消**。只改善 TTFD 而把 1.2s
  推给用户第一次点词，一律判不合格。
- `Displayed` / `am start -W` 的 `TotalTime` 只作旁证，不参与判定。

---

## 3. 红线 1 的保全（必须最先回答）

延迟 import 后最大的风险不是性能，而是**把「未加载」误判成「可用」**。规则如下：

1. **显式状态机**，唯一真相源放在 `model_loader`：
   - `UNKNOWN`：尚未尝试导入
   - `LOADING`：后台导入中
   - `AVAILABLE`：`import spacy` 成功
   - `MISSING`：`import spacy` 抛 `ImportError`，或后续模型加载确定失败
2. **终态只能由真实 import 产生**：在真正执行 `import spacy` 的代码处 `try/except
   ImportError → MISSING`。**禁止**用 `importlib.util.find_spec()` 之类的「看起来有包」
   探测来宣称 `AVAILABLE`——find_spec 成功不等于 import 成功，且 Chaquopy 的 importer
   行为与 CPython 不完全一致。
3. **`process_german_text()` 的分支规则**：
   - `AVAILABLE` → spaCy 路径；
   - `MISSING` → 纯 Python 路径（红线 1 原语义）；
   - `UNKNOWN` / `LOADING` → **同步完成导入并阻塞到终态**后再判定；
     严禁把 `UNKNOWN` / `LOADING` 当作 `AVAILABLE` 直接走 spaCy。
4. **后台预热只能改变触发者，不能改变判定**：预热线程中的任何异常都必须把状态落到
   `MISSING` 并留日志，不允许静默停留在 `UNKNOWN`。
5. **可观测性**：`/api/settings`、`/api/syntax/spacy-status` 必须反映终态；`LOADING`
   要显式表达为加载中，而不是提前宣称 `spacy`。
6. **回归测试（实施 PR 必须新增）**：
   - monkeypatch 使 `import spacy` 抛 `ImportError` ⇒ 首次分析仍走纯 Python、不抛异常；
   - 预热线程失败 ⇒ 状态为 `MISSING`、首次分析仍走纯 Python；
   - 首次分析早于预热完成 ⇒ 行为等价于同步导入（不得误判 AVAILABLE）。

> 一句话：**红线 1 的判定从「导入期副作用」改为「显式终态」，语义不变、位置可变。**

---

## 4. 候选方案与代价

### 方案 A：只延迟 `import spacy`（fastapi / database 保持现状）

- **做法**：把 spacy 导入从模块顶层挪到 `ensure_spacy()`；导入期只初始化状态机；
  首次分析或后台预热触发导入。
- **削减**：约 1.09s 的库导入（ADR-0020 记录值），减去首次分析同步兜底的等待。
- **红线 1**：影响最大。必须完整落地 §3 状态机；`processor` / `model_loader` /
  `syntax_tree` 三处引擎判定都要改，否则会重现 ADR-0028 的「同进程两套引擎」矛盾。
- **代价**：改动面最集中也最危险；测试面包含降级、并发、状态可观测性。

### 方案 B：分阶段 import（先起 HTTP，再加载 database → spacy）

- **做法**：`server.py` 顶层只保留 FastAPI 必需项；`delector.core.database` 初始化与
  spacy 导入拆到「监听开始之后」的阶段；`start.py` 写端口文件、壳开始轮询不依赖它们。
- **削减**：把「监听前置」这段串行切开，HTTP 更早就绪，壳的轮询可提前命中。
- **红线 1**：database 延迟不涉及引擎判定；spacy 仍按 §3 状态机。风险在于首次请求
  早于初始化完成时必须同步兜底，否则会 500。
- **代价**：`start.py` / `server.py` 启动顺序重排；必须守住 architecture.md 的既有约束
  ——「不要在 import 期做可能抛异常的事」「`init_db()` 顶层 seed 的失败必须可见」。
- **备注**：只动启动顺序，不改变「何时算可用」的语义边界，是三者中最容易验收的。

### 方案 C：后台线程预热 import，完成后切换判定

- **做法**：进程启动即起线程 import 重依赖，主线程继续；判定读状态机。
- **削减**：**不减少 CPU 总量**，只与 splash / JS 加载重叠；与 Python 服务自身启动争
  GIL 与 CPU，净收益不确定（参见 `startUpWebView` 负结果的同构失败）。
- **红线 1**：必须保证首次分析早于预热完成时同步等待，而不是误判。
- **代价**：并发状态最多、测试面最大；若实现不严，会把缺失暴露推迟到首次点词。

| 维度 | A 只延迟 spacy | B 分阶段 import | C 后台预热 |
| --- | --- | --- | --- |
| 改动层 | `nlp_engine` 内部 | 启动顺序（`start.py` / `server.py`） | 启动并发 + 状态机 |
| 预计削减 | ≈1.09s 中的可重叠部分 | database + spacy 的前置串行 | ≈0（只重叠，不减少） |
| 首次分析风险 | 中（同步兜底） | 中（请求早到需兜底） | 高（并发窗口） |
| 红线 1 风险 | 高（判定点搬家） | 中（仅 spacy 部分） | 高（UNKNOWN 误判） |
| 测试面 | 大 | 中 | 最大 |

---

## 5. 历史教训（反面依据，必须写进决策）

ADR-0028 §4.2 记录：把 spaCy 惰性化之后，**冷启到首次分析完成从 2837ms 升到 3977ms**
（+1140ms）。启动环节看似受益，成本被原样搬到用户第一次点词的那一刻。

由此得到三条硬约束：

1. **延迟 ≠ 削减**，只是搬家；只要用户很快会触发首次分析，搬家净收益可能为负。
2. 任何 import 迁移都必须**同时量首次分析**；只量启动的结论一律不成立。
3. Python 进程内的线程并行受 GIL/import lock 限制，不能把 import CPU 变成免费。

---

## 6. 决策

本 ADR 状态 **Proposed**，**不实施**。若启动优化继续推进：

- 优先评估 **方案 B**：它只重排启动顺序，不改变引擎可用性语义，验收边界最清晰。
  > 2026-11-09 已实测：方案 B 判负（TTFD 改善 <100ms，seed 单项仅 72ms/110ms），
  > 数字见 0032-python-off-first-screen-path §3.2；分支 `perf/adr-0031-plan-b` 不合并。
- **方案 A / C** 无论何时实施，都必须先交付 §3 的状态机与红线 1 回归测试，再谈收益。
- 实施必须走独立 PR，按 §2 的双指标验收；未达标即回滚，不留「部分受益」的中间态。

---

## 7. 后果

**正面**

- 给出可判定的通过/放弃阈值，避免「感觉快了」式结论。
- 把红线 1 的判定点从隐式导入副作用变成显式终态，后续任何惰性化都不必再猜语义。

**负面 / 风险**

- 状态机引入 `LOADING` 等新可观测状态，`/api/settings` 与前端需要容忍并正确展示。
- 若实现不严，spaCy 缺失会推迟到首次分析才暴露，用户感知为「第一次点词特别慢」。

**回滚**

- 全部为进程内改动，回滚 = revert 单个实施 PR；无数据迁移、无 ABI/打包面变化。

## 8. 未决问题

1. `delector.core.database` 的 `init_db()` 能否安全移到监听之后（顶层 seed 的失败可见语义如何保持）。
2. Chaquopy 下延迟 import 是否会引入额外的 dex/asset 解压成本（**未证实**，需实测）。
3. 「首次分析」的统一定义（首次点词 / 首次 `/api/analyze` / 首次句法请求）需在实施 plan 中钉死。
