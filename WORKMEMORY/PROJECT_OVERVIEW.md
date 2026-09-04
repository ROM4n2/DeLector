# PROJECT_OVERVIEW — DeLector（60 秒 primer）

> 首次生成：2026-09-04（bootstrap 会话从 AGENTS.md / README / ADR-0005 提炼）。
> 维护约定：交接或重大里程碑后由当前 agent 就地更新，不追加副本。

## 一句话定位

**DeLector** = 德语精读 + 歌德/德福备考 Web App。FastAPI + spaCy + SQLite 单文件后端，
原生 JS ES Modules 单页前端，`python start.py` → `http://localhost:8000`。
三种形态共用同一后端：桌面 Python / Windows 便携版（PyInstaller）/ Android（Chaquopy）。

## 必读锚点（按需深入）

- `AGENTS.md`（项目根）：机器可读项目快照——技术栈表、NLP 降级路径警告、Android 互锁版本表、API 路由全览、数据库 schema。**读头部 30 行起步**，全文很长。
- `FEATURES.md`：产品特性全览。
- `docs/specs/`、`docs/plans/`：设计与实施计划（含 ledger）。
- ADR 存于 vault：`vault://08-Projects/DeLector/01-ADR/`（0001 工作台核心词 / 0002 scope 控制 / 0004 LAN 同步 Stage B / 0005 导航重布局与多等级可扩展，未提交状态）。
- `.vault-exec-ledger.json`：/vault-exec 任务台账。

## 当前状态（2026-09-04 快照）

- 分支 `master`（HEAD: 路线 B 落地）。
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
- 测试基线：**全量 565 全绿**（116.45s，基线 559 -> 565 +6），10/10 `tools/*.mjs` 探针全绿；pre-commit 密钥守卫有效，工作区干净。
- 下一步待办：路线 C（24 维语法雷达与精读长难句 AST 闭环）。

## 本项目高频坑（详见 AGENTS.md 对应节）

1. NLP 降级路径**静默**切到纯 Python 时语法标注会**给错**（不是精度低，是错）——改标注逻辑前看 `nlp_engine` 字段。
2. Android 侧 spaCy 模型加载有三级回退 + `extractPackages` 三包缺一不可；`spacy.load("名称")` 在 Android 上必炸。
3. `app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由，否则全 API 405。
4. versionCode 编码 `major*10000+minor*100+patch`，有测试守卫；keystore 只从环境变量读，丢失即包名报废。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 work.log。
