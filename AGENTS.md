# AGENTS.md — DeLector 项目 AI Agent 入口

> **每次开新 agent 对话时，第一步必须读这个文件。** 本文件只做路由（同 CLAUDE.md 形态）：
> 项目状态、架构、惯例、待办全在下游文档——从这里重建完整 context 不超过 60 秒。

## 共享工作记忆 (WORKMEMORY)

- 进入会话先读 `WORKMEMORY/INDEX.md` → `WORKMEMORY/PROJECT_OVERVIEW.md`（当前状态 / 红线速查 / 开放待办都在这）→ `work.log` 尾部 50 行；发现未闭合 WORK_START 先询问用户。
- 工作中：决策/踩坑/交接 MUST 以 ≤4KB 事件追加 `WORKMEMORY/work.log`（schema 见 `WORKMEMORY/PROTOCOL.md`）。

## 文档路由

| 需要什么 | 去哪 |
| --- | --- |
| 当前状态 / 红线速查 / 开放待办 / 项目定位 | `WORKMEMORY/PROJECT_OVERVIEW.md` |
| 架构细节：技术栈 / NLP 降级 / Android 互锁 / DB schema / API 全览 / 前端拓扑 / LAN 同步 / FSRS / 完形 / 切句 | `docs/agents/architecture.md` |
| 安全守卫 / 本机环境 / 打包 / Agent 工作惯例 | `docs/agents/ops.md` |
| 版本历史与发布记录 | `README.md` Roadmap（changelog）+ git tag |
| 产品特性全览 / 设计与实施计划 | `FEATURES.md`；`docs/specs/`、`docs/plans/` |
| 语义知识检索与沉淀 | `search_vault` MCP 或 `python d:\Obsidian\Coding\scripts\search-vault.py`；成熟知识走 `/vault-save` |

---

_项目一句话：德语精读 + 歌德/德福备考 Web App；`python start.py` → http://localhost:8000。
本文件由 agent 维护，**保持纯路由形态**——内容只放下游文档，不要往回搬；就地修改，勿追加副本。_
