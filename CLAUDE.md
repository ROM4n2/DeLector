# Project Guidelines

## 文档路由（先读这个）

- 本仓 agent 文档入口是 `AGENTS.md`（纯路由表）：架构 / 运维 / 发版 / 文档落位规则都在那里。进入会话先读它，再按需下沉到具体文档。

## 工程规范与避坑检索 (Coding Vault Invariants)

> `$WIKI_PATH` 指向知识库根目录，由**用户级环境变量**提供；未设置时向用户询问，**勿把机器专属绝对路径写回仓库**。

- 核心规范源：`$WIKI_PATH/AGENTS.md`
- 检索避坑规范：调用 `search_vault` MCP，或 `python "$WIKI_PATH/scripts/search-vault.py" "<报错/模式关键词>"`
- 发现新踩坑自动沉淀：调用 `save_inbox_draft` 写入 `$WIKI_PATH/99-Inbox/`，或手工落草稿 `$WIKI_PATH/99-Inbox/YYYY-MM-DD-{topic}.md`
- 主动体检与待办挖掘：`python \"$WIKI_PATH/scripts/vault-proactive-scan.py\"`
- 全库健康体检：`python \"$WIKI_PATH/scripts/vault-health-check.py\"`

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` → `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。
- 语义知识检索：调用 `search_vault` MCP 或 `python "$WIKI_PATH/scripts/search-vault.py" "<关键词>"`；成熟知识沉淀走 `/vault-save`。
