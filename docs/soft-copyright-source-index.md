# 软件著作权申报 · 源代码鉴别材料清单

> 本清单是仓库内可评审的索引：列明建议提交的源代码文件、顺序、逐文件功能说明与设计决策（ADR）映射，
> 以及明确的排除项。它不复制任何申报制式草稿、也不另起一套源码选择逻辑——实际生成申报材料时，
> 以工具产出的代码清单为执行态单一真值，本清单与它选择口径一致、互不读写。
>
> 编制口径：通用"前 30 页 / 后 30 页"。若申报机构对页数、字号、每页行数或格式另有细则，以机构要求为准并在此登记偏差。
> 分页按 A4 正文约 50 行/页估算；实际页码随字号与打印设置浮动，提交前以导出 PDF 的真实页序复核。

## 一、作品与著作权人

- 作品名称：DeLector · 德语欧标沉浸精读与考点剖析系统
- 著作权人：席皓宇（自然人）
- 开发语言：Python 3.10/3.11（后端）+ 原生 JavaScript ES Modules（前端）
- 说明书：见 [`USER_GUIDE.md`](USER_GUIDE.md)（与本清单一同交付；如该文件尚未出现，说明其所在 Task 分支尚未合入）

## 二、选择原则

1. **只提交自研实现**：`delector/` 应用包与 `static/js/` 原生前端模块是本作品原创代码。
2. **按独创性密度排序**：优先自研 NLP/句法引擎、形态学、路由与服务，再放数据种子与前端入口。
3. **前后各 30 页**：前 30 页为算法内核（最能体现独创性），后 30 页为业务路由、服务与前端交互。
4. **排除第三方运行时与生成物**：详见第四节，这些不是本作品源代码。
5. **逐文件标注 ADR**：功能设计 rationale 以 `docs/adr/INDEX.md` 的仓内副本为准，编号与标题不改写。

## 三、建议提交清单（按此顺序）

### 前 30 页 · 算法内核

| 序 | 文件 | 功能一句话 | 对应 ADR |
| --- | --- | --- | --- |
| 1 | `delector/nlp_engine/linguistics.py` | 形态学与搭配引擎：强变化动词三态、复合词递归拆解、介词支配格与固定搭配 | ADR-0012 / ADR-0013 |
| 2 | `delector/nlp_engine/syntax_tree.py` | 五场域（VF/LK/MF/RK/NF）切分与五种从句 AST 抽象语法树分析 | ADR-0007 / ADR-0028 |
| 3 | `delector/nlp_engine/processor.py` | NLP 处理主流程：句子切分、词法标注、降级路径编排 | ADR-0027 / ADR-0028 |
| 4 | `delector/nlp_engine/syntax_tables.py` | 句法拓扑与从句类型的数据表驱动定义 | ADR-0007 |
| 5 | `delector/nlp_engine/syntax_fields.py` | 五场域字段映射与色谱标注逻辑 | ADR-0007 |
| 6 | `delector/nlp_engine/case_resolution.py` | 德语格位消解与名词短语性数格判定 | ADR-0012 |
| 7 | `delector/nlp_engine/model_loader.py` | 德语 NLP 模型加载与零副作用就绪探针（单档 sm、失败负缓存） | ADR-0027 / ADR-0028 |
| 8 | `delector/core/lexicon.py` | 词库单一真相化与等级判定数据驱动 | ADR-0011 / ADR-0012 |
| 9 | `delector/core/vocab_pool.py` | 统一词池架构：工作台与主背词路径共享身份池 | ADR-0016 |
| 10 | `delector/core/database.py` | SQLite 连接管理、建库与写路径事务边界 | ADR-0014 |
| 11 | `delector/core/vocab_identity.py` | 词条身份归一与跨源去重键 | ADR-0011 / ADR-0016 |
| 12 | `delector/services/syntax_score.py` | 长难句 7 维难度评分与 CEFR 级别估算 | ADR-0007 |

### 后 30 页 · 路由、服务与前端

| 序 | 文件 | 功能一句话 | 对应 ADR |
| --- | --- | --- | --- |
| 13 | `delector/routes/articles.py` | 精读文章 GET、惰性重算与 AI 语法剖析端点（含无 Key 降级） | ADR-0026 / ADR-0033 |
| 14 | `delector/routes/writing.py` | 写作工坊后端：实时规则诊断、AI 润色与快照端点 | — |
| 15 | `delector/services/writing.py` | 写作诊断规则引擎、Inlay Hints 与句子级 diff 改写 | — |
| 16 | `delector/routes/syntax_hard.py` | 长难句精读工坊：跨语料挑句、拆解揭示与成绩落盘 | ADR-0007 |
| 17 | `delector/routes/search.py` | 多源全文检索端点（内存扫描、变音折叠、加权排序） | ADR-0014 |
| 18 | `delector/services/search.py` | 词条/例句/搭配/语料四组内存扫描与排序实现 | ADR-0014 |
| 19 | `delector/services/companion_agent.py` | 伴学 Agent 原生 Tool Calling 与真流式双通道 | ADR-0025 |
| 20 | `delector/services/companion_proposal.py` | HITL 生词卡提议的生成、校验与审阅流程 | ADR-0025 |
| 21 | `delector/routes/companion.py` | 伴学会话与页面级能力分区端点 | ADR-0025 |
| 22 | `delector/core/update_download.py` | 应用内更新：安全下载器、字节数与 sha256 双校验 | ADR-0034 / ADR-0017 |
| 23 | `delector/core/update_apply.py` | 跨平台安装状态机与原子替换 | ADR-0034 |
| 24 | `delector/server.py` | FastAPI 服务装配与静态资源挂载（末位路由红线） | — |
| 25 | `static/js/reader.js` | 阅读页交互：词阶热力、五场域抽屉联动与影子跟读 | ADR-0026 / ADR-0007 |
| 26 | `static/js/rd-syntax.js` | 前端句法树渲染与光圈联动 | ADR-0007 |
| 27 | `static/js/cards.js` | 3D 卡盒与 FSRS 复习交互 | — |
| 28 | `static/js/writer.js` | 内联 IDE 写作编辑器、波浪线与 Inlay Hints 渲染 | ADR-0029 |
| 29 | `static/js/wb-sync.js` | 局域网静默同步（Stage A 镜像 + Stage B WebRTC 兜底） | ADR-0003 / ADR-0004 |
| 30 | `static/js/update-flow.js` | 前端应用内更新流程与失败提示 | ADR-0034 |

> 说明：表内"对应 ADR"为空者表示该文件的行为未由单独 ADR 记录，仍为本作品原创实现；
> ADR 编号可在 [`docs/adr/INDEX.md`](adr/INDEX.md) 查到标题与状态。清单顺序即建议的提交顺序。

## 四、明确排除项（非本作品源代码）

| 排除对象 | 实测规模 | 理由 |
| --- | --- | --- |
| `android/` 下的 Python 依赖与生成物 | 7797 个 `.py` | Chaquopy 第三方运行时与构建产物，非本作品源码 |
| 全仓 `.pyc` 字节码 | 7379 个 | Python 编译生成物，非源码 |
| `requirements*.txt` / `requirements.lock.txt` / `skills-lock.json` 等锁文件 | — | 依赖版本清单，非本作品实现 |
| `.venv/`、`.agents/`、`.git/` | — | 本机工具态与版本库元数据 |
| `软件著作权申请资料/` | — | 申报提交材料（含权利人信息），不入库 |
| `static/` 下第三方前端库（若有 vendored 文件） | — | 第三方依赖，非本作品源码 |

## 五、存在性核验记录

第三节 30 个文件均经逐路径存在性检查通过（核验命令与输出见本 Task 执行台账）。
说明书 `docs/USER_GUIDE.md` 由 Task 1 产出、在独立分支上，合并后即与本清单同仓。
第四节的 7797 / 7379 为核验当日实测值，仅用于说明排除规模，不是本作品代码量。
