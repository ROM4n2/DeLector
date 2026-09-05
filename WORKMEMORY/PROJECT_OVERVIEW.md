# PROJECT_OVERVIEW — DeLector（60 秒 primer）

> 首次生成：2026-09-04（bootstrap 会话从 AGENTS.md / README / ADR-0005 提炼）。
> 维护约定：交接或重大里程碑后由当前 agent 就地更新，不追加副本。

## 一句话定位

**DeLector** = 德语精读 + 歌德/德福备考 Web App。FastAPI + spaCy + SQLite 单文件后端，
原生 JS ES Modules 单页前端，`python start.py` → `http://localhost:8000`。
三种形态共用同一后端：桌面 Python / Windows 便携版（PyInstaller）/ Android（Chaquopy）。

## 必读锚点（按需深入）

- `AGENTS.md`（项目根）：**纯路由入口**（2026-09-05 二轮瘦身，~30 行）——只有 WORKMEMORY 约定与文档路由。架构在 `docs/agents/architecture.md`，安全/环境/工作惯例在 `docs/agents/ops.md`，版本历史在 README Roadmap。状态、红线、待办都在本文件，勿往 AGENTS 回填。
- `FEATURES.md`：产品特性全览。
- `docs/specs/`、`docs/plans/`：设计与实施计划（含 ledger）。
- ADR 存于 vault：`vault://08-Projects/DeLector/01-ADR/`（0001 工作台核心词 / 0002 scope 控制 / 0004 LAN 同步 Stage B / 0005 导航重布局与多等级可扩展，未提交状态）。
- `.vault-exec-ledger.json`：/vault-exec 任务台账。

## 当前状态（2026-09-05 快照）

- 分支 `master`（HEAD=`9341b43`，**tag `v5.3.0` 已 push**：发布收口 v5.2.0 后 30 commits——ADR-0006 工作台重塑 + ADR-0007 语法雷达 + A2 全域贯通）。
- **重大里程碑**：
  1. **ADR-0005 备考域 Phase 1 全量落地（PR #25 已合入 master）**：
     - 「场景工具 + 独立备考域」双带架构落地，A1 听说读写各模块迁入 `view-exam` 独立域。
     - 考纲目录 `exam_catalog.py` 种子化与 `/api/exams/catalog` 路由上线。
     - 泛化模考成绩表 `exam_trials` 上线并幂等迁移历史记录。
  2. **路线 B 落地：背词工作台视觉 Token 归一与考纲词表契约（台账 6/6 全绿）**：
     - Academic Modern Editorial 共享 Token 层抽离（`static/css/tokens.css`）。
     - 背词工作台（`workbench.html`）全面移植暖纸墨水 Editorial 配色与排印，暗色模式暖调化。
     - 考纲与生词只读契约端点 `GET /api/cards/vocab` 上线并具备内存级解析缓存。
     - 工作台顶栏扩展「⭐ A1 核心 / A1 全量 / 精读生词」三档位，保持 13 条切片护栏 100% 零漂移。
  3. **ADR-0006 落地：背词工作台 Zettelkasten 实体学术卡片箱与心流优先轻量化导航全面落地（台账 6/6 全绿）**：
     - 全局字体族体系（`--serif` / `--sans` / `--mono`）规范化，彻底消除硬编码中文字体与 Georgia，画布收敛为 960px 实体期刊留白。
     - 出版物下划线轻量 Tab 导航与聚焦顶栏重塑，剥离厚重阴影与大圆角容器。
     - Zettelkasten 纯白学术抽认卡纸张层叠翻转交互，40px 衬线词头与典雅排印。
     - 矿物植物印章式浅柔评分座（四级彩色柔和印章底座 + 键盘角标快捷键），彻底剔除粗厚纯红绿黄实心块。
     - 自测题选项、拼写输入框、KPI 统计与词库浏览表全面 Editorial 风格细化。
     - 13/13 处动态切片护栏 100% 保护通过，0 破坏、0 漂移。
  4. **路线 C 落地：Grammatik-Radar 精读语法雷达全量落地（台账 6/6 全绿）**：
     - ADR-0007 句法行内幽灵微胶囊主动触发：消除 600ms hover 被动弹出抽屉的打扰感，改为行内幽灵胶囊按钮（Quiet Ghost Pill on Hover），光标悬停句子优雅淡入 `🌳 句法`，显式点击才展开右侧句法抽屉，零心流打扰，保护生词查词抽屉状态。
     - 语料语法统计落盘：SQLite `corpus_syntax_stats` 表 + `POST /api/syntax/stats` 与 `GET /api/syntax/stats` 端点，文章精读时客户端自动聚合 6 大语法维度指标（从句复合度、五场域展开率、句框跨度比、关系从句率、虚拟语气率、被动被动态率）并上报落盘与缓存。
     - 蜘蛛图雷达：语法抽屉嵌入轻量无外部依赖 SVG 蛛网雷达图（#grammar-radar-panel），动态对比「本文维度 vs 语料平均基准」，带维度释义 tooltip 与墨水期刊质感。
  5. **A2 词汇与全域背词系统扩展（方案 B：全域贯通落地，台账 5/5 全绿）**：
     - 歌德 A2 974 个考纲词汇全量规范化提取，497 个名词准确拼装定冠词（如 das Abenteuer）且首字母大写，动词/形容词保持小写。
     - 服务端提供 `GET /api/a2/vocab` 端点并在 `exam_catalog.py` 中注册 A2 考纲词表模块（动态推导 974 题量），通过 PyInstaller 打包注册守卫。
     - 背词工作台（`workbench.html`）顶栏扩展第 4 档位「📘 A2 词库」，异步按需同步服务端 A2 词条并持久化到本地进度，13/13 处切片护栏 100% 绝对保护通过。
     - 备考域（`view-exam`）激活 A2 考纲选项卡，`a1_cards.js` 扩展支持 A2 考纲词卡（3D 扑克翻转、例句发音、网格模式、搜索过滤与加入复习盒）。
- 测试基线：**全量 582 全绿**（137.53s，基线 574 -> 582 +8），10/10 `tools/*.mjs` 探针全绿（含 13/13 处切片护栏 100% 保护）；pre-commit 密钥守卫有效，工作区干净。
- 发布面：正式版 **v5.3.0**（源码版）；Android versionName 5.3.0 / versionCode 50300（CI 从 tag 推导）；桌面端正常，`python start.py` → `http://localhost:8000`。
- **开放待办**：① v5.3.0 打包资产——Windows/macOS/Linux 便携包与 Android APK 待打包、GitHub Release 资产待补录（README 下载表已标注「源码版·打包中」）；② 新功能候选：多模态听力微训 / 语料长难句强化立项。

## 红线速查（详情见 `docs/agents/architecture.md` / `ops.md`）

1. NLP 降级路径**静默**切到纯 Python 时语法标注会**给错**（不是精度低，是错）——改标注逻辑前看 `nlp_engine` 字段。
2. `app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由，否则全 API 405。
3. Android 五项互锁（py3.10 / minSdk24 / spacy3.8.7 / CI spaCy pin / arm64-only）动一个查全部；`spacy.load("名称")` 在 Android 必炸，要用 `importlib.import_module(名称).load()`；`extractPackages` 三包缺一不可。
4. versionCode 编码 `major*10000+minor*100+patch`，有测试守卫；keystore 只从环境变量读，丢失即包名报废。
5. 发版先跑「版本面五件套」（sw.js / index.html / build.gradle / README / 本文件当前状态），`test_writer_mobile.py` 两条测试锁死；tag 必须打在含 bump 的 commit 上。
6. `?v=` 查询串已退役：缓存闸 = 服务端 `Cache-Control: no-cache` + 安卓 `static.version` 重解包。
7. 敏感设置与删除操作仅 127.0.0.1 可写（`_require_localhost`），局域网 403；新端点遵守该闸。
8. pre-commit 密钥扫描必须启用，禁 `--no-verify`。
9. import 期不得联网、不得抛异常（Android 启动卡死的历史根因）。
10. 切句只有 `syntax_tree.split_sentences_pure_python()` 一处实现，别造第二份。
11. 跨边界契约（前端 body ↔ 后端模型）必须行为探针验证，字符串存在断言是死测（2026-09-02 事故）。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 work.log。
