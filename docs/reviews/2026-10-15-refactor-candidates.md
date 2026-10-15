# 重构候选评估（DeLector，非在途面）

**Date**: 2026-10-15 · 分支 `chore/swarm-audit-master` @ `64e2fc8`（不碰在途分支）
**方法**：LOC 实测（`wc -l`）+ 两个侦察席位按「职责数 / 耦合 / 重复 / 在途冲突」定性排序
**核心结论**：**最大的文件恰恰最不该动**（前三大都是纯数据），真正该动的是 `core/database.py`（2,809 行 / 86 def / 9 组职责 / 32 处被 import）与前端**备份键集合的双实现**（与 P1-1 同源）。

---

## 0. 先纠正指标：LOC 大 ≠ 该重构

| 文件 | LOC | 判定 | 处置 |
|---|---|---|---|
| `delector/data/core_dict_ext.py` | 3,978 | **DATA-BLOB**（0 def、1 个 `CORE_VOCAB_EXT`、auto-generated 已标注） | 不动 |
| `delector/data/official_vocab.py` | 3,064 | **DATA-BLOB**（文档明写纯数据/零函数/零副作用） | 不动 |
| `delector/data/official_vocab_rich.py` | 3,049 | **DATA-BLOB**（富字段 side-car） | 不动 |
| `delector/data/encounter_seed_dict.py` | 1,493 | **DATA-BLOB**（真源与重建命令已写明） | 不动 |
| `delector/data/prep_dict.py` | 933 | **DATA-BLOB**（0 def） | 不动 |

**隐藏成本（为什么不拆数据）**：`tests/test_server.py` 的 `data_dict_modules` 是**硬编码集合**（当前 16 个，`:4582-4611`）；每新增一个数据分片 MUST 同步 **3 个交付配置面**（Windows PyInstaller / Linux+macOS workflow / Android 拷贝打包）+ 这一个守卫集合；该测试自述「本地全绿、打包后 ModuleNotFoundError」（`:4570-4577`）。⇒ **纯数据文件不得仅因 LOC 大就拆**。

---

## 1. 后端候选榜（值不值得动，降序）

| # | 文件 | LOC | 类型 | 职责 | 被 import | 在途冲突 | 一句话建议 |
|---:|---|---:|---|---|---:|---|---|
| 1 | `delector/core/database.py` | 2,809 | LOGIC-GOD-FILE | 9 组 / **86 def** | **32** | 否（API 被在途面用） | **最值**：按 连接/迁移 → 领域仓储 → 备份 → 导出/种子 切，保留兼容 façade |
| 2 | `tests/test_server.py` | 7,271 | TEST-BLOB | 14 组 / ≥301 用例 | 0 | ⚠️ 含 ai-polish 测试段 | 值：**按被测面原样搬用例**（不改用例本身），润色段等在途落地 |
| 3 | `delector/nlp_engine/processor.py` | 661 | MIXED | 4 组 / 11 符号 | 6 | 间接 | 值：切「模型生命周期 / CEFR 策略数据 / 文本流水线」，先冻结加载接口 |
| 4 | `tests/test_german_workbench.py` | 3,913 | TEST-BLOB | 8 组 / 105 用例 | 0 | 否 | 值：按 TTS / 核心词 / 队列 / 迁移 / 同步 / rich 回填 切 |
| 5 | `delector/nlp_engine/syntax_tree.py` | 1,545 | MIXED | 4 组 / 11 符号 | 7 | 否 | 值：先分 分类表 / 拓扑场 / Clause AST；模型加载与 `processor` 统一边界 |
| 6 | `delector/nlp_engine/linguistics.py` | 1,543 | MIXED | 4 组 / 13 符号 | 6 | 间接 | 值：按 不规则动词 / 复合词 / 扩展词典 / 介词矩阵 切（先数据后算法） |
| 7 | `tests/test_desktop_shell.py` | 2,664 | TEST-BLOB | 8 组 / 89 用例 | 0 | 否 | 值（独立批次）：按 日志/退出/托盘/GUI 启动/server-only/AppID 切 |
| 8 | `delector/routes/main.py` | 3,115 | LOGIC-GOD-FILE | 12 组 / **70 routes** | 3 | ⚠️ **直接重叠** | **等在途落地后**：按领域 router 切；当前严禁碰 ai-polish/SSE 窗口 |
| 9 | `delector/services/writing.py` | 1,424 | MIXED | 4 组 / 27 def | 7 | ⚠️ **直接重叠** | **等裁判集落地后**：按 语法规则族 / 聚合器 / A1 格式裁判 切 |
| 10 | `delector/data/a1_hoeren_dict.py` | 1,547 | MIXED | 4 组 / 3 def + 数据表 | 3 | 否 | 等第三套同类引擎或下次改判分：抽与 Lesen **完全同构**的查询/脱敏/判分（`:1423/:1436/:1475` vs Lesen `:1103/:1116/:1148`），**数据不动** |

**候选 #1 `database.py` 的证据**：86 个顶层函数横跨 —— 路径/连接与双库建表迁移（`:46-581`）· 设置与鉴权（`:585-843`）· 文章与 encounter 种子（`:846-1209`）· Anki 与音频缓存（`:1212-1432`）· 备份/还原（`:1432-1910`）· 考试/训练记录（`:1928-2196`）· 词汇契约与富字段 …… 且与 `nlp_engine/processor.py` 存在**已知双向耦合**（`core/database.py:23` ⇄ `nlp_engine/processor.py:16`）。

---

## 2. 前端候选榜

| # | 文件 | LOC | 类型 | 职责 | 重复/风险 | 在途冲突 | 一句话建议 |
|---:|---|---:|---|---|---|---|---|
| 1 | `static/js/cards.js` | 1,324 | 页面脚本 | 42 函数 / 23 onclick / 3 段 | **备份 + LS 键扫描「第二实现」** | 无 | **最值**：键集合单点化（不是拆文件） |
| 2 | `static/index.html` | 3,158 | 页面壳（0 JS） | 9 view / **214 处 onclick** | 全局函数名与 markup 硬耦合 | 无 | 中风险：按 view 拆标记，**必须保留** `main.js` 的 window 接线面 |
| 3 | `static/js/companion.js` | 782 | 页面脚本 | 12 处裸 localStorage | 键名硬编码 10 个 | 无 | **纯收益**：键名收进常量表 + 注册进备份白名单 |
| 4 | `static/js/main.js` | 1,203 | 共享/接线层 | 25 函数 / 1 个 `Object.assign(window,…)`（`:958`） | 214 onclick 的**唯一接线点** | 无 | 先加守卫再动：exposer 是全站交互单点故障 |
| 5 | `static/german/workbench.html` | 4,730 | **单文件 PWA** | 1 内联 script（822-4620）+ 内嵌 SW；115 函数 | 备份第 2 处、TTS、api 裸 fetch 20 处 | 无 | **最痛但别先动**（见下） |
| 6 | `static/js/writer.js` | 1,657 | 页面脚本 | 47 函数 / 5 段 | — | ⚠️ **ai-polish 段 1089-1487** | 等 `a1-judge-expansion` 落定 |
| 7 | `static/js/encounter.js` | 1,485 | 页面脚本 | 61 函数 / 10 段 | 少 | 无 | 不值：边界已清 |
| 8 | `static/js/reader.js` | 1,403 | 页面脚本 | 40 函数 / 10 段 | TTS 第 4 处（ShadowPlayer） | 无 | 不值：段内聚；TTS 是**合并**不是拆文件 |

**候选 #1 的真实价值（与 P1-1 同源）**：`cards.js:1005-1008` 硬编码 `BACKUP_LS_PREFIX="delector_"` / `BACKUP_LS_WORKBENCH_PREFIX="wb."` / `BACKUP_LS_TRANSIENT`，`:1010` 手扫 localStorage；而 `workbench.html:4347/4362/4382/4386/4441` 是**同一关注点的第二套实现**，两边**各自硬编码 `wb.` 前缀** ⇒ 任一侧加键，另一侧静默漏备份。这正是 P1-1（密钥 `wb.pair.v1` 经前端备份绕过后端白名单）的结构性成因 ⇒ **修 P1-1 时顺手把键集合单点化**，收益最大、风险最低。

**候选 #5 为什么别先动**：`workbench.html` 单文件内塞了种子词数据（825-905）· g2p IPA 引擎（906-984）· 存储与键表（1031-1040）· 归一迁移（1041-1350）· wbsync（1359-1451）· WebRTC/RTC（1452-1686）· IndexedDB（1687-1850）· TTS 三层（1936-2284）· FSRS-6（2285-2372）· 复习/自测/统计/词库 · LAN 短码同步（3863-4093）· 导入导出（4094-4503）· PWA（4635-4729）—— **但拆文件会让 4 个测试文件全红**：`test_german_workbench.py`（28 处引用，含「`index("const tryServer") < index("const tryOnline")`」这类**全文位置断言**）、`test_workbench_tokens.py`（20）、`test_a1_workbench_source.py`（7）、`test_frontend_module_graph.py:401-433`（按**行号**钉 `saveXxx` 挂 `wbsync.push()`）。⇒ **先做：把整文件/行级探针改成按段读入**，再谈切分。

---

## 3. 明确不建议动

**后端**：五个纯数据模块（见 §0）· `a1_lesen_dict.py`（应与 Hoeren **配对**抽公共逻辑，不单独拆）· `tests/test_ci_hardening.py`（1,380，等 >2,000 或新增第三类门禁）· `tools/verify_windows_portable.py`（924，职责单一）· `agent/internal/job/encounter.go`、`pythonsvc/supervisor.go`（458/449，不因 Python 重构顺带动 Go 门禁）。

**前端**：`encounter.js` / `reader.js`（段内聚，拆只增跳转成本）· `listen-lab.js`、`hard-sentences.js`（被 `test_frontend_module_graph.py:503-573` **三重钉死**：非孤岛 / 导出齐全 / 无环；且 `listen-lab.js:13-16` 明写「自管播放队列、不重构 ShadowPlayer」是**有意为之**的复制）· `a1_cards.js`（38 处 onclick 全靠 innerHTML，拆标记=重写渲染，收益为负）· `core.js`（它是**收敛目标**，不是切分对象）。

---

## 4. 建议的重构顺序（与在途面 / P0-P1 协调）

1. **现在就做（与 P0/P1 同批，纯收益）**：前端**备份键集合单点化**（`cards.js` ↔ `workbench.html` 合一处）+ `companion.js` 键名常量表 —— 直接消掉 P1-1 的结构性成因。
2. **P0-1 修完之后**：`core/database.py` 按职责切（**切之前先补契约测试**：`_BACKUP_TABLES` ↔ `RestoreReq` 一致性、备份往返、白名单），否则切模块会顺手丢掉不变量。
3. **在途落地之后**：`routes/main.py` 按领域 router 切（避开 ai-polish/SSE 窗口）· `services/writing.py` 按规则族切（等裁判集第二轮）。
4. **独立批次**：测试文件按被测面切（`test_server.py` / `test_german_workbench.py` / `test_desktop_shell.py`）—— **只搬归属、不改用例**。
5. **等条件**：`workbench.html`（先把整文件/行级探针改按段读入）· `a1_hoeren/lesen_dict` 的公共 exam dataset engine（等第三套同类或下次同时改判分）。
6. **永不**：纯数据模块（除非生成耗时/多人冲突成为**实测**问题）。

## 5. 打包面结论（重构前必读）

- **前端拆文件**：`static` 整目录 add-data（`package_windows.py:324`、`build-release.yml:107/206`）⇒ 打包**零改动**；`APP_NEEDLES` 不含前端 ⇒ 零影响；会红的是 `test_frontend_module_graph.py`（新模块须被 import、不得成环、不得空）。
- **后端拆/新增模块**（尤其 `delector/data/*`）：MUST 同步 **3 个交付配置面 + 1 个守卫集合**（`tests/test_server.py` 的 `data_dict_modules`），否则「本地全绿、打包后 ModuleNotFoundError」。
- `index.html` 动标记时**别碰** `:40` 的版本串与 `sw.js:3` 的 `CACHE_NAME`（`test_writer_mobile.py` 断言二者一致）。
