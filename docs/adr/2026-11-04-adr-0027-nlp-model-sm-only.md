# ADR-0027: NLP 模型档位定案为 `de_core_news_sm`

- **状态**：ACCEPTED
- **日期**：2026-11-04
- **决策者**：席皓宇 (Haoyu Xi), Hermes Agent
- **关联 ADR**：
  - [[0008-go-agent-runtime-architecture]]（历史记录：NLP 引擎选型时写的是 md，本 ADR 不改写历史）
  - [[0018-performance-measurement-before-runtime-swap]]（性能实测基线，含模型加载耗时口径）

---

## 1. 背景与问题陈述 (Context and Problem Statement)

`delector/nlp_engine/processor.py` 曾按 `("de_core_news_md", "de_core_news_sm")` 顺序加载：
md 优先，sm 只在 md 加载失败时兜底。但**全链路实际只有 sm**：

- CI（`.github/workflows/ci.yml`）自动下载的是 `de_core_news_sm`；
- 应用首次启动的自动下载只装 `sm`；
- Android 打包（`spacy==3.8.7` + Chaquopy）预置的是 `sm`；
- 新建 uv 环境按 `requirements` 安装后也只装 `sm`。

因此 "md 优先" **从未在真实运行中生效**，只是被 sm 静默兜底。代码声称的策略与运行事实
长期不符 —— 这不是精度问题，而是**事实陈述问题**：任何人读代码都会得出"应用在用 md"的
错误结论，排障与性能归因也会被带偏。

本 ADR 定案：只支持 `de_core_news_sm`，删除 md 优先分支，并把"是否值得为精度引入 md"
留作显式的、未验证的 OPEN 项，而不是继续以代码默认策略的形式存在。

## 2. 决策 (Decision)

1. `processor.SPACY_MODEL_NAME = "de_core_news_sm"` 成为**唯一事实源**；
2. 删除 `SPACY_MODEL_CANDIDATES` 候选元组、`AUTO_DOWNLOAD_MODEL` 独立下载口径，以及
   `syntax_tree.get_spacy_nlp()` 的 md → sm 双段回退；
3. 运行期本地加载与自动下载共用同一常量；本地加载失败时自动下载**同一个 sm**，
   再失败则硬失败（沿用既有失败语义）；
4. `try_load_nlp_no_download()` 本地加载失败仍返回 `None`，**纯 Python 降级路径保持不动**
   （Android/离线面的既有行为不在本决策范围内）；
5. 全仓可执行引用（README / CONTRIBUTING / Dockerfile / `docs/agents/` / `tools/` 基准脚本）
   统一为 sm 口径；历史 ADR、归档计划与 CHANGELOG 的 md 记录**只保留、不改写**。

## 3. 理由 (Rationale)

- **md 与 sm 是分别训练的独立模型**，不是"同一模型的放大版"。md 的增量价值主要在**静态
  词向量**（相似度、近义、聚类类任务）；本应用的核心链路要的是分词、词性标注、依存句法树
  与难度榜，属 tagger / parser 范畴，md 的收益只是"可能略准"，且**从未在真实语料上量化**。
- **体积成本确定，精度收益不确定**：md 体积是 sm 的数倍；Android 包的体积预算已按 sm 定案，
  为一个未经量化的"略准"再多背几十 MB 不划算。
- **一致性收益确定**：单一事实源消除了"代码说 md、运行时是 sm"的长期事实偏差，也让自动下载、
  文档与基准脚本的口径第一次对齐。

## 4. 被否方案 (Rejected Alternatives)

1. **保留 md 优先，但环境只有 sm（即现状）** —— 否决。
   代码与运行事实不符，等于对读代码的人撒谎；排障时会把"精度/行为差异"错误归因到 md。
2. **桌面用 md、移动用 sm 的分叉方案** —— 否决。
   两套模型意味着两套精度基线、两套性能基线与两套排障路径；而 md 的收益尚未量化，
   分叉只会把不确定性扩散到发布面，不解决任何已证实的问题。
3. **直接把 sm 换成 md** —— 否决。
   体积涨数倍、Android 预算被打破、收益未量化；且与"先量化再改"的工程纪律冲突。

## 5. 后果 (Consequences)

- 正面：模型口径单一、可复核；自动下载与文档一致；新增守卫可防止 md 分支回潮。
- 负面/代价：若未来真实语料证明 md 对句法树或难度判定有显著收益，需要先做一次对照实验，
  再走新的 ADR 重新评估；本决策**不预设**该实验的结论。
- 不变：纯 Python 降级路径、三级模型加载回退（`spacy.load` → `importlib` → 绝对路径）、
  Android 不下载策略，全部保持原样。

## 6. OPEN：sm vs md 的对照实验（未验证、未执行）

- **问题**：用 `hard-sentences` 真实难句做 sm vs md 的对照，量化分词、词性、依存句法树与
  难度判定的差异，判断 md 的"略准"是否值得其体积成本。
- **形态**：一次性离线脚本，**不进生产代码**、不改变运行时默认；结论若支持引入 md，
  必须另立 ADR 重新决策，而不是直接改常量。
- **状态**：**未验证、未执行**。本 ADR 不包含任何"md 更准/更差"的实测结论。

## 7. 守卫 (Guards)

`tests/test_nlp_model_sm_only.py` 钉住：

1. `SPACY_MODEL_NAME == "de_core_news_sm"`，且 `SPACY_MODEL_CANDIDATES` / `AUTO_DOWNLOAD_MODEL` 不存在；
2. 运行期模块（processor / syntax_tree）与 `tools/*.py` 不含 `de_core_news_md` 包名；
3. 自动下载只尝试 sm 一次；失败路径抛 `RuntimeError` 而不是静默降级；
4. `try_load_nlp_no_download()` 失败返回 `None` 且绝不触发下载。
