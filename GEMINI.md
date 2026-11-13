# GEMINI.md — DeLector 项目 AI Agent 规则（Gemini CLI / Antigravity）

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md` → `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。

## 项目机器可读快照

每次开新 agent 对话时，读 `AGENTS.md`（头部 30 行起步）与 `WORKMEMORY/PROJECT_OVERVIEW.md` 重建 context。

## 工程规范与本机知识库

> 本仓库**不包含**个人知识库的路径、目录结构与内容。若本机配置了知识库 MCP
> （`search_vault` / `save_inbox_draft`）或 `/vault-save` 命令，按其自身说明使用；
> 未配置就跳过本节。**勿把机器专属路径写回仓库。**
