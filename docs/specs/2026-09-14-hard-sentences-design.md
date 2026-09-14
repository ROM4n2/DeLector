# DeLector 长难句精读工坊设计规格（Hard-Sentence Reading Lab）

- 日期：2026-09-14
- 状态：待批准（vault-spark Phase 4 产出）
- 关联：ADR-0007（句法幽灵胶囊/抽屉架构）、Grammatik-Radar（`corpus_syntax_stats` 文章级画像）、ADR-0010 遇见区（encounter 分级材料源）、听力微训工坊（`/api/listen` 模式参照）

---

## 1. Problem Statement & User Value

**问题**：Grammatik-Radar 只做**文章级画像展示**（6 维聚合），不帮学习者行动——精读撞上长难句没有定向抓手：哪句最难、难在哪、怎么拆、怎么复习。阅读桥在"句子级"断链。

**价值**：
- 把雷达的静态展示变成**句子级精读训练闭环**：难度评分 → 挑选 → 尝试拆解 → 揭示句法树 → 逐词释义 → 入复习盒
- 与听力微训并列成为备考域第二训练带；材料复用现成语料（articles / OFFICIAL_CORPUS / encounter 分级短文）
- **目标用户时机**（A1/A2 背词过渡期）：形态定位为**精读脚手架**而非虐题——默认按级别门控，句子带难度分与 CEFR 估算标签，不强推超纲句

**不做（scope 控制）**：
- 不建独立"长难句题库"（从语料/encounter 现成文本按需派生）
- 不做跨语料持久化难度索引（按需计算 + 内存缓存，YAGNI）
- 句子级特征不落库（收敛为：训练记录表 + 复习盒复用 grammar_cards）
- 不改 Grammatik-Radar 既有展示（reader 内嵌清单面板为后续增量，不进 MVP）
- 不新建卡种表（复习盒复用 `grammar_cards` SRS 流程）

---

## 2. User Journey & Core Flow

### 入口
备考域新增「✍️ 长难句精读」带（与「🎧 听力微训」并列）。

### 3 步核心流
1. **选材料源**：语料文章 / encounter 分级短文 / 全语料难度榜（按 level 过滤）
2. **句子卡片流**：逐句卡——原句（难度分 + 级别标签）→ 先"尝试拆解"（隐藏句法树，识别主句/从句）→ 揭示句法树（复用 ADR-0007 抽屉渲染）+ 逐词释义（复用查词链路）→ 可选「加入复习盒」
3. **落盘反馈**：会话结束 `hard_sentence_trials` 记录；已入盒句在复习卡域按 SRS 复习

### 卡片交互
- **卡面**：原句（按难度分降序）、CEFR 估算标签、复杂度维度 chip（从句深度/被动/虚拟式/VL 句框/长度）
- **尝试拆解模式**：默认隐藏句法树，用户先勾选"主句位置"（或口头找主句后点揭示）；揭示后显示 clause_tree 与 VL 标注
- **入复习盒**：复用 `saveGrammar` 语义写 `grammar_cards`（句子文本 + 难度画像进卡面）

---

## 3. Architecture & Data Models

### 后端（2 leaf 模块 + 1 路由，照 `/api/listen` 模式）

**`delector/services/syntax_score.py`**（纯函数，可含慢路径缓存）
- `score_sentence(analysis: dict) -> SentenceScore`：从 `analyze_syntax_tree` 输出提取特征 → 加权难度分 0–100 + 维度明细
  - 特征：clause_tree 深度、从句复合度（clause 数）、五场域覆盖、句框跨度（VL/verb-last）、被动、虚拟式、关系从句、句长（词数）
  - 权重设计对齐 Grammatik-Radar 维度口径（可跨域对照）
- `estimate_level(score: float) -> str`：分数 → CEFR 带（A1/A2/B1/B2 粗分，供门控）
- `rank_sentences(text: str) -> list[SentenceScore]`：`split_sentences_pure_python`（红线 10 唯一实现）→ 逐句 `analyze_syntax_tree`（spaCy/纯 Python 双路径）→ 评分 → 降序
- **红线 1 纪律**：分析结果标注来源路径（`spacy`/`pure`）；纯 Python 降级时分数仅作参考，响应带 `path` 字段供 UI 提示

**`delector/routes/syntax_hard.py`**（prefix `/api/syntax`，注册进 register_routes，main 之前）
- `GET /api/syntax/hard-sentences?source=&source_id=&level=&min_score=&limit=` → `{items:[{sentence, score, level, dimensions, path, source, source_id}]}`：source 枚举 `article`/`encounter`/`all`；按需计算 + 进程内存缓存（键=source+id，TTL 短）
- `GET /api/syntax/hard-sentences/detail?source=&source_id=&sentence_index=` → 单句完整分析（clause_tree/topology/词元，供卡片揭示用）
- `POST /api/syntax/hard-sentence/trials` body `{source, source_id, sentence_index, level, score, revealed, duration_sec}` → `{trial_id}`（本地训练记录，非敏感，不挂闸）
- 入复习盒：**复用既有** `saveGrammar` 端点（无新端点），前端按既有卡字段拼装

**数据模型**：`hard_sentence_trials`（对齐 `listen_trials` 模式）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER PK | |
| source | TEXT | 'article' \| 'encounter' |
| source_id | INTEGER | 材料 id |
| sentence_index | INTEGER | 句在材料中的序号 |
| level / score | TEXT / REAL | 估算级别 / 难度分 |
| revealed | INTEGER | 是否揭示过句法树（0/1） |
| duration_sec | INTEGER | 会话秒数 |
| created_at | TEXT | ISO |

迁移：`database.py` 加幂等建表 + backup/restore schema 清单补条目 + 打包/注册守卫同步（route 集 `syntax_hard`、service 集 `syntax_score`）。

### 前端

**`static/js/hard-sentences.js`**（新模块，ES Module，无外部依赖）
- 材料源选择器 + 句子卡片流 + 尝试拆解/揭示 + 难度维度 chips + 「加入复习盒」（复用 `saveGrammar`）
- 释义：复用查词链路（`/api/lookup/vocab` 或 reader 查词抽屉形态）
- 会话成绩：`POST /api/syntax/hard-sentence/trials`（失败静默降级）
- 挂载：备考域新带 + `main.js` 视图映射；UI 对齐 Editorial token、触控 ≥44px

### 与既有资产的关系
| 资产 | 角色 |
| --- | --- |
| `syntax_tree.analyze_syntax_tree` / `split_sentences_pure_python` | 双路径分析 + 红线 10 切句 |
| `grammar_cards` + `saveGrammar` | 复习盒（长难句卡复用，不新建表） |
| `corpus_syntax_stats` / Grammatik-Radar | 维度口径对齐 + 文章级画像参照 |
| encounter 短文 / articles / OFFICIAL_CORPUS | 材料源（复用分级文本） |
| 听力微训工坊 | 训练带模式参照（引擎+路由+卡片流） |

---

## 4. Edge Cases & Resilience

- **红线 1（降级给错）**：纯 Python 降级路径分析可能出错——响应带 `path`，UI 对 `pure` 句显示「近似分析」提示，评分仅参考
- **红线 10**：切句只走 `split_sentences_pure_python`，禁止自造
- **性能**：全文逐句分析是重计算——内存缓存（source+id 键）+ `limit` 护栏（默认 ≤50 句）+ 按需懒算
- **材料删除/更新**：detail 404 给人话，不崩面板
- **空语料/无超纲句**：清单空态提示（"没有超过当前难度的句子"）
- **A1/A2 过渡用户**：默认 level 门控（默认 A2+，可切全部），不碾压
- **trial 落盘失败**：静默降级（本地成绩仍展示），不阻断
- **重复入盒**：复用 grammar_cards 幂等语义（同句已入盒显示「已加入」）
- **跨边界契约**：hard-sentences/detail/trials 的 body↔前端契约必须行为探针验证（红线 11）

---

## 5. Test Strategy

- **`tests/test_syntax_score.py`**（TDD）：评分特征→分映射单测（深度/被动/虚拟式/VL/长度各维度）、`estimate_level` 带划分、`rank_sentences` 降序与红线 10 切句复用断言
- **`tests/test_syntax_hard_api.py`**：路由契约——hard-sentences 列表/过滤（source/level/min_score/limit）/detail/detail 404/trials 落盘与回读（TestClient `127.0.0.1` + `setdefault` env 隔离）、register_routes 挂载与打包守卫同步
- **`tests/test_hard_sentences_probe.mjs`**（node:vm 直跑真源码）：材料选择/卡片流/拆解揭示/入盒调用/成绩汇总——**钉死前端↔后端契约**（红线 11），含变异验证
- **`tests/test_frontend_module_graph.py`**：纳入 `hard-sentences.js` 依赖检查
- **全量回归**：pytest 全量 + ruff 零告警 + Mypy 零错误 + Go 三门禁不受影响

---

## 自审（vault-spark Phase 4 Self-Review）

- [x] 无 TODO/TBD 占位
- [x] 无内部矛盾（材料源/评分/落盘/复习盒一致）
- [x] 无 scope creep（不做清单显式列出；C 的"统"收敛为训练记录 + 复习盒复用，不建新卡种/不持久化句子特征）
- [x] 红线对齐：切句唯一实现（红线 10）、降级路径标注（红线 1）、跨边界契约行为探针（红线 11）、写操作闸纪律（trials 非敏感不挂闸）
