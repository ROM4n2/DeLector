# ADR-0027: NLP 模型档位定案为 `de_core_news_sm`

- **状态**：ACCEPTED
- **日期**：2026-11-04
- **决策者**：席皓宇 (Haoyu Xi), Hermes Agent
- **关联 ADR**：
  - 0008-go-agent-runtime-architecture（历史记录：NLP 引擎选型时写的是 md，本 ADR 不改写历史）
  - 0018-performance-measurement-before-runtime-swap（性能实测基线，含模型加载耗时口径）

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
留作显式项；该项已在合并后补做一次性对照实验（111 句真实语料），结论见 §6。

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
  与难度榜，属 tagger / parser 范畴，md 的收益只是"可能略准"；2026-11-04 的 111 句真实
  语料对照实验（见 §6）显示该收益仅覆盖 3/111 句且方向不稳，而成本是确定的。
- **体积成本确定，精度收益不确定**：md 体积是 sm 的 2.82×（21.16 → 59.61 MB）；Android
  包的体积预算已按 sm 定案，为一个仅覆盖约 2.7% 句子的"略准"再多背几十 MB 不划算。
- **一致性收益确定**：单一事实源消除了"代码说 md、运行时是 sm"的长期事实偏差，也让自动下载、
  文档与基准脚本的口径第一次对齐。

## 4. 被否方案 (Rejected Alternatives)

1. **保留 md 优先，但环境只有 sm（即现状）** —— 否决。
   代码与运行事实不符，等于对读代码的人撒谎；排障时会把"精度/行为差异"错误归因到 md。
2. **桌面用 md、移动用 sm 的分叉方案** —— 否决。
   两套模型意味着两套精度基线、两套性能基线与两套排障路径；而 md 的收益实测仅覆盖
   约 2.7% 的句子（§6），分叉只会把不确定性扩散到发布面，不解决任何已证实的问题。
3. **直接把 sm 换成 md** —— 否决。
   体积涨 2.82×、Android 预算被打破、收益仅覆盖 3/111 句且方向不稳（§6）；且与"先量化再改"的
   工程纪律冲突。

## 5. 后果 (Consequences)

- 正面：模型口径单一、可复核；自动下载与文档一致；新增守卫可防止 md 分支回潮。
- 负面/代价：若未来要重新评估 md，必须先修评分器对解析噪声的敏感性（§7），再走新的 ADR；
  §6 的对照实验已执行并给出"维持 sm"的结论，本 ADR 不再以"未量化"作隐含前提。
- 不变：纯 Python 降级路径、三级模型加载回退（`spacy.load` → `importlib` → 绝对路径）、
  Android 不下载策略，全部保持原样。

## 6. 对照实验（已执行）：sm vs md —— 结论维持 sm

- **语料**：111 句去重后真实语料（A 库内材料 58 + B 官方真题语料 23 + C 基准脚本语料 30；
  原始 152 句去重 41 句）。仓库内没有静态 `hard-sentences` 数据文件，A 即该接口的真实输入
  全量；A/B 不足 100 句，故用仓库工具链内嵌语料补足。
- **形态**：一次性离线脚本，**不进生产代码**、不改变运行时默认；spaCy 3.8.7 / Python 3.11.8，
  单模型独立子进程，同一台机器。
- **证据**：`D:\Code\_artifacts\nlp-tier-compare-20261104\`（`report.md`、`raw.json`、
  `env.txt`、`compare.py`）。
- **结论**：md 的收益不足以覆盖成本，**维持 sm**；决策状态保持 `ACCEPTED`。

关键数字：

| 维度 | 结果 |
| --- | --- |
| 分词 | 111/111 句完全相同 |
| 难度等级 | 107/111 一致；4 句翻转（\|Δ分\| 18.5 / 14.5 / 12.5 / 7.5） |
| 可分动词 | 10/10 句两模型都给出 `svp`+head 信号（仅 sm 0 句、仅 md 0 句）；`sep_lemma` 一致 8/10 |
| 人工目检（非金标准） | 4 句翻转中 3 句 md 标注更合理（如 sm 把 `kommst` 标 ADV、`müsste` 标 NOUN）；第 4 句不确定 |
| 收益覆盖 | 3/111 ≈ 2.7% 的句子 |
| 磁盘 | 21.16 → 59.61 MB（2.82×） |
| RSS 峰值增量 | 128.42 → 310.04 MB（2.41×） |
| 冷加载 | 0.67 → 1.28 s（1.91×） |
| 单句推理中位 | 5.7 → 6.0 ms |

- **关键新发现**：更合理的解析反而把难度分从 B1 降到 A2（53.5/35.0），说明 `score_sentence`
  对解析噪声敏感——**换模型前应先修评分器**（见 §7）。
- **未验证 / 边界**：
  - 无逐 token 人工金标准，只有 4 句翻转的目检 ⇒ 只能说"更合理"，不能说"更准"；难度等级是
    DeLector 的启发式评分，不是真值。
  - 语料 B2 为 0 句、B1 仅 sm 7 / md 8 句；翻转发生在少数 B1 边界句上，不能据此断言真实 CEFR。
  - md 的 310.04 MB 峰值内存与 1.28 s 冷加载在 Android / 移动端**未实测**。
  - md 词向量对相似度、聚类类下游任务的收益**未测**；本实验只测 tagger / parser 链路。
- **复算**（PowerShell，摘自报告 §9；真模型只从官方 GitHub Release 取 3.8.0 wheel）：

```powershell
$ART = 'D:\Code\_artifacts\nlp-tier-compare-20261104'
uv venv "$ART\.venv" --python 3.11.8
Invoke-WebRequest 'https://github.com/explosion/spacy-models/releases/download/de_core_news_sm-3.8.0/de_core_news_sm-3.8.0-py3-none-any.whl' -OutFile "$ART\wheels\de_core_news_sm-3.8.0-py3-none-any.whl"
Invoke-WebRequest 'https://github.com/explosion/spacy-models/releases/download/de_core_news_md-3.8.0/de_core_news_md-3.8.0-py3-none-any.whl' -OutFile "$ART\wheels\de_core_news_md-3.8.0-py3-none-any.whl"
uv pip install --python "$ART\.venv\Scripts\python.exe" "spacy==3.8.7" "$ART\wheels\de_core_news_sm-3.8.0-py3-none-any.whl" "$ART\wheels\de_core_news_md-3.8.0-py3-none-any.whl" "pydantic>=2,<3" "psutil" click
& "$ART\.venv\Scripts\python.exe" "$ART\compare.py"
```

## 7. 后续待办：先修评分器对解析噪声的敏感性（OPEN，未执行）

- **问题**：§6 的翻转里，更合理的句法分析（`auswerten` 由 VVFIN 改为 VVINF）反而把分数从
  53.5/B1 拉到 35.0/A2；`score_sentence` 的阈值对 tag/dep 噪声敏感，可能把难度判定建立在
  模型的解析不确定性上。
- **状态**：**OPEN、未执行**。本 ADR 只登记该发现，不存在"已修复"的结论。
- **方向（未验证）**：换模型前先量化 `score_sentence` 对 tag/dep 扰动的敏感度并加固权重/阈值；
  验收标准是同一句在 sm 与 md 下的等级翻转显著减少。

## 8. 供应链风险：PyPI 同名包不是真模型（记录，未修复）

- `de-core-news-sm` / `de-core-news-md` 在 PyPI 上的 `999.9.9` 是 JetBrains 发布的
  **Dependency Confusion 占位 stub**，不是 spaCy 官方模型。
- 本实验的真模型来源：spaCy 官方 GitHub Release 的 3.8.0 wheel
  （`https://github.com/explosion/spacy-models/releases/download/...-3.8.0/...-py3-none-any.whl`），
  未安装 PyPI stub。
- 口径要求：涉及模型安装的文档与脚本 MUST 指向官方 GitHub Release 或
  `python -m spacy download`，**不得**写成含糊的"从 PyPI 安装"。

## 9. 守卫 (Guards)

`tests/test_nlp_model_sm_only.py` 钉住：

1. `SPACY_MODEL_NAME == "de_core_news_sm"`，且 `SPACY_MODEL_CANDIDATES` / `AUTO_DOWNLOAD_MODEL` 不存在；
2. 运行期模块（processor / syntax_tree）与 `tools/*.py` 不含 `de_core_news_md` 包名；
3. 自动下载只尝试 sm 一次；失败路径抛 `RuntimeError` 而不是静默降级；
4. `try_load_nlp_no_download()` 失败返回 `None` 且绝不触发下载。
