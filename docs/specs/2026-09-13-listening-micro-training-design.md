# DeLector 听力微训工坊设计规格（Listening Micro-Training Lab）

- 日期：2026-09-13
- 状态：待批准（vault-spark Phase 4 产出）
- 关联：v4.8.0 听写工坊设计（`2026-08-30-v4.8.0-corpus-grammar-diktat-design.md` §3.3，实现从未落地，本规格复活并扩展）；ADR-0010 遇见区（材料源）；ADR-0005 备考域（挂载位）

---

## 1. Problem Statement & User Value

**问题**：真实用户（女友，安卓端）处 A1/A2 背词期，歌德 A1 **Hörverstehen 听力是四科之一（25 分）**。当前听力只有一次性考试模式（`a1_hoeren.js`，15 题/套），**没有碎片化日常微训**——备考只能靠考试，平时零训练；且考试题与背词/分级短文脱节。

**价值**：
- 贴合用户当前阶段（背词→短文过渡路径上的听力补位）
- 碎片时间可用：一次微训 3-5 分钟短会话
- 复用零音频资产（TTS 按需合成），材料与遇见区分级短文同源，跨功能协同

**目标用户**：安卓端背词用户（首要）；桌面端同享。

**不做（scope 控制）**：
- 不建独立听力材料库（复用 encounter 短文 + a1_hoeren 音频文本）
- 不做音频资产缓存/预合成
- 不重构 reader 的 ShadowPlayer（lab 自管播放队列，复用 `playGermanAudio` 层）
- 不改 a1_hoeren 考试模式
- 不做 AB 循环波形可视化（v4.8.0 设计的波形进度条裁剪掉）
- 不做新题生成（不产新听力题库）

---

## 2. User Journey & Core Flow

### 入口
备考域 `view-exam` 新增「🎧 听力微训」带（与现有听说读写模块并列），或在 `a1_hoeren` 区旁加 tab——选型在计划阶段定，spec 以「独立入口挂进备考域」为准。

### 3 步核心流
1. **选材料**：微训面板列「遇见区分级短文（A1/A2）+ A1 听力音频句库」清单，按 level 过滤
2. **选模式**：精听/影子跟读（L）· 听写诊断（D）· 听力填空（C）
3. **训练并即时反馈**：播放 → 交互 → 诊断反馈（逐字分类 / 填空对错）→ 本会话成绩落盘 `listen_trials`

### 三模式交互

**Mode L · 精听/影子跟读**
- 句子列表逐句播放（复用 `playGermanAudio` 三层 TTS 兜底），当前句高亮，支持变速（0.75x–1.25x）/重复/循环
- 影子跟读节奏：播放后留跟读停顿（对齐 ShadowPlayer shadow 模式语义，但队列在 lab 内自管）

**Mode D · 听写诊断**
- 文本隐藏 → 逐句播放 → 用户键入复现 → `POST /api/listen/diagnose` → **逐字分类反馈**：正确 / 变音（ü→u）/ 大小写（der→Der）/ 词尾屈折（-en→-e）/ 缺漏 / 多余
- 不惩罚大小写/变音（分类提示而非判错）；顺序错乱 = 缺漏+多余组合归因

**Mode C · 听力填空**
- 服务端 `make_cloze(sentence, level)` 挖词成空（动词/名词按 level 策略；短句不挖）→ 听后填 → 校验（复用 diagnose 语义比对）

### 成绩
会话结束汇总（正确词数/总词数/分数/耗时）→ `POST /api/listen/trials` 落盘；`GET /api/listen/trials` 历史列表（先只读展示，不做趋势图）。

---

## 3. Architecture & Data Models

### 后端（C 统一引擎，只加 2 个 leaf 模块 + 1 条路由，不扩 DB 面太多）

**`delector/services/listen.py`**（纯函数，无 DB 无联网）
- `diagnose_diktat(expected: str, actual: str) -> ListenDiagnosis`：词级 LCS 对齐（DP 实现参照 writer.js 词级 LCS 思路）+ 逐字分类归因
  - 分类规则：完全一致→correct；仅变音差（ü/u、ä/a、ö/o、ß/ss）→umlaut；仅大小写差→case；同 lemma 词尾差→inflection；目标有输入无→missing；目标无输入有→extra
  - 复用 `essay_diff.diff_sentences` 的句子级 LCS 结构（v4.8.0 设计即指定复用 essay_diff LCS）
- `make_cloze(sentence: str, level: str) -> ClozeItem`：按词性/频率策略挖空（动词优先，名词次之；句子 <5 词不挖）
- 输出 Pydantic 模型：`ListenDiagnosis{expected, actual, tokens: [TokenResult{token, status, hint}]}`、`ClozeItem{text_with_blanks, answer, source}`

**`delector/routes/listen.py`**（prefix `/api/listen`，注册进 `register_routes`，在 main 之前）
- `GET /api/listen/materials?level=`：聚合材料清单——encounter 短文（`/api/encounter/texts` 同源数据，含 level）+ a1_hoeren 音频句库（`a1_hoeren_dict`，`audio_text_de` 切句）
- `GET /api/listen/materials/{source}/{id}`：单材料详情，含**服务端切句**（`syntax_tree.split_sentences_pure_python`，红线 10 唯一实现）与句子列表
- `POST /api/listen/diagnose`：body `{expected, actual}` → 本地诊断（无联网、无本机闸——纯文本比对各处可用）
- `POST /api/listen/trials`：body `{mode, source_type, source_id, level, total, correct, duration_sec}` → 落 `listen_trials`
- `GET /api/listen/trials`：最近历史（数量上限）

**数据模型**：`listen_trials` 表（对齐 `exam_trials` 模式）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER PK | |
| mode | TEXT | 'listen' \| 'dictation' \| 'cloze' |
| source_type | TEXT | 'encounter' \| 'hoeren' |
| source_id | INTEGER | 对应材料 id |
| level | TEXT | A1/A2 |
| total / correct | INTEGER | 总词数 / 正确词数 |
| score | REAL | correct/total |
| duration_sec | INTEGER | 会话秒数 |
| created_at | TEXT | ISO |

迁移：`database.py` 加建表迁移（幂等，参照既有表迁移模式）。

### 前端

**`static/js/listen-lab.js`**（新模块，ES Module，无外部依赖）
- 自管播放队列（**不重构** reader ShadowPlayer；复用 `playGermanAudio` 层）
- 三模式控制器 + 听写输入框 + 逐字反馈渲染（correct/umlaut/case/inflection/missing/extra 六色胶囊）
- 材料选择器（level 过滤）+ 会话成绩汇总
- 挂载：index.html 备考域容器 + `main.js` 视图映射

### 与既有资产的关系
| 资产 | 角色 |
| --- | --- |
| `player.js playGermanAudio` | 句子级播放 + 三层 TTS 兜底（Android Native → `/api/audio/tts` → Web Speech） |
| `essay_diff.py` / writer.js 词级 LCS | 诊断引擎算法参照 |
| encounter 短文（`data/encounter_seed_dict.py` + 用户导入） | 分级材料源 |
| `a1_hoeren_dict` 的 `audio_text_de` | A1 听力原句材料源 |
| v4.8.0 听写设计（§3.3） | 逐字分类诊断规格出处（Umlaut/Case/Spelling/Missing） |

---

## 4. Edge Cases & Resilience

- **TTS 全链路失败**：三层兜底均不可用时停止推进 + 可见提示（对齐 ShadowPlayer `speakFailed` 语义），不静默空转
- **无网络**：诊断与填空校验为本地纯函数（无网络）；TTS 是唯一网络依赖，Android Native TTS 免网
- **真机 TTS 未验证**：Chaquopy 真机 TTS 链路仍属发版后真机点检项（既有遗留），lab 上线后并入点检清单
- **材料删除/更新**：material 详情 404 时给"材料不可用"人话，不崩面板
- **听写输入规范**：大小写/变音不判错（分类提示）；空输入/全非德语字符 → 提示并跳过
- **填空挖空边界**：句子 <5 词不挖；挖空答案含标点不参与比对
- **trial 落盘失败**：静默降级（本地成绩仍展示），不阻断会话
- **并发**：lab 单会话单队列，播放令牌失效机制（参照 ShadowPlayer `_reqToken` 陈旧响应丢弃）
- **跨边界契约**：diagnose/trials/materials 的 body↔前端契约必须行为探针验证（红线 11）

---

## 5. Test Strategy

- **`tests/test_listen_engine.py`**（TDD，先红后绿）：`diagnose_diktat` 分类单测——变音（ü→u）/大小写（der→Der）/词尾（-en→-e）/缺漏/多余/完全正确/顺序错乱；`make_cloze` 挖空策略（短句不挖、动词优先）
- **`tests/test_listen_api.py`**：路由契约——materials 装配（encounter+hoeren 聚合、level 过滤）、diagnose 形状、trials 落盘与查询（TestClient `127.0.0.1` 双客户端 + `setdefault` env 隔离纪律）、register_routes 挂载守卫
- **`tests/test_listen_lab_probe.mjs`**（node 直跑真源码）：模式切换/播放队列/听写提交/逐字反馈渲染/成绩汇总——**钉死前端↔后端契约**（红线 11）
- **`tests/test_frontend_module_graph.py`**：纳入 `listen-lab.js` 依赖检查（非孤岛、无循环）
- **全量回归**：`pytest` 全量 + `ruff check .` 零告警 + Go 三门禁不受影响

---

## 自审（vault-spark Phase 4 Self-Review）

- [x] 无 TODO/TBD 占位
- [x] 无内部矛盾（三模式、材料源、表结构一致）
- [x] 无 scope creep（不做清单显式列出；v4.8.0 裁剪教训吸收）
- [x] 与红线对齐：切句唯一实现（红线 10）、跨边界契约行为探针（红线 11）、`_require_localhost` 纪律（新端点全读操作或纯比对，无写面暴露局域网）
