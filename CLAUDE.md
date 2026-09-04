# Project Guidelines

## 工程规范与自动化工具路径 (Coding Vault Invariants)

- **核心规范源**：`d:\Obsidian\Coding\AGENTS.md`
- **精准规则检索**：`python d:\Obsidian\Coding\scripts\search-vault.py "<报错/模式关键词>"`
- **主动体检与待办挖掘**：`python d:\Obsidian\Coding\scripts\vault-proactive-scan.py`
- **全库健康体检**：`python d:\Obsidian\Coding\scripts\vault-health-check.py`
- **发现新踩坑自动沉淀**：写草稿至 `d:\Obsidian\Coding\99-Inbox\YYYY-MM-DD-{topic}.md`

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` → `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。
- 语义知识检索：调用 `search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py "<关键词>"`；成熟知识沉淀走 `/vault-save`。
