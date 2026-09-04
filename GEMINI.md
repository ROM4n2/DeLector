# GEMINI.md — DeLector 项目 AI Agent 规则（Gemini CLI / Antigravity）

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` → `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。
- 语义知识检索：调用 `search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py "<关键词>"`；成熟知识沉淀走 `/vault-save`。

## 项目机器可读快照

每次开新 agent 对话时，读 `AGENTS.md`（头部 30 行起步）与 `WORKMEMORY/PROJECT_OVERVIEW.md` 重建 context。

## 工程规范

- 核心规范源：`d:\Obsidian\Coding\AGENTS.md`
- 精准规则检索：`python d:\Obsidian\Coding\scripts\search-vault.py "<报错/模式关键词>"`
- 发现新踩坑自动沉淀：写草稿至 `d:\Obsidian\Coding\99-Inbox\YYYY-MM-DD-{topic}.md`
