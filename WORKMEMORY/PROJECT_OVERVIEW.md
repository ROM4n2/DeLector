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

- 分支 `master`，最近版本线 v5.1.0（LAN 静默同步 Stage B WebRTC）→ v5.1.1（bugfix 收口）。
- **进行中主线：ADR-0005 备考域骨架**——「场景工具 + 独立备考域」两带导航重构，
  备考域骨架与导航入口已落地（commit 692e8ea + Task 1 ledger 回填 d68a834），
  工作树有 `static/index.html` 与 `static/js/` 多文件未提交改动。
- 下一步（ADR-0005 待办清单）：A1 四功能迁入备考域、exam catalog 种子、
  路由参数化 `/api/exams/{level}/{module}`、组件提取刀、共享 token 抽取。
- 测试基线：v5.1.0 全量 487 全绿；提交守卫 pre-commit 密钥扫描启用。

## 本项目高频坑（详见 AGENTS.md 对应节）

1. NLP 降级路径**静默**切到纯 Python 时语法标注会**给错**（不是精度低，是错）——改标注逻辑前看 `nlp_engine` 字段。
2. Android 侧 spaCy 模型加载有三级回退 + `extractPackages` 三包缺一不可；`spacy.load("名称")` 在 Android 上必炸。
3. `app.mount("/", StaticFiles(...))` 必须是 `server.py` 最后一个路由，否则全 API 405。
4. versionCode 编码 `major*10000+minor*100+patch`，有测试守卫；keystore 只从环境变量读，丢失即包名报废。

## 工作方式

- 提交 Conventional Commits；禁止 `--no-verify`。
- 语义知识检索：`search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`。
- 会话事件按 `PROTOCOL.md` 记入本目录 work.log。
