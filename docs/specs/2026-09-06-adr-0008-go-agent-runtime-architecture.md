# ADR-0008: Go Agent Runtime + Python NLP Engine 混合架构

> **Status:** Accepted (2026-09-06, /vault-grill 共识)
> **决策者:** Haoyu Xi
> **关联:** DeLector 职业转型 — Go 后端 + AI Agent 方向

---

## Context

DeLector 是一个 Python 全栈德语学习 Web App（FastAPI + spaCy + SQLite），当前为单体架构。职业目标是 Go 后端 + AI Agent 工程师。需要一条既能保留现有 Python 语言学算力、又能产出 Go 工程经验的重构路径。

### 事实基线

| 维度     | 现状                                                       |
| -------- | ---------------------------------------------------------- |
| 后端框架 | FastAPI + Uvicorn (async)                                  |
| NLP 引擎 | spaCy de_core_news_md（依赖分析、POS、形态学、五领域分析） |
| 数据     | 556 条不规则动词三式词典 + FSRS 间隔重复                   |
| 测试     | 582 全绿（28 测试文件）                                    |
| 打包形态 | PyInstaller 桌面版 / Chaquopy Android / Docker             |
| AI 集成  | DeepSeek（OpenAI 兼容 API）                                |

---

## Decision Drivers

### 用户与产品体验层

- **简历叙事**：需要一个能讲 30 分钟的架构故事，而不是"我把 Python 翻译成了 Go"
- **面试官视角**：绞杀者模式 ≠ HTTP 代理包装，Go 层必须做 Python 做不了的事
- **跨平台分发**：当前 PyInstaller 打包笨重，Go 单二进制是质的提升

### 技术与工程实现层

- **并发模型差异**：Python asyncio 单线程事件循环 vs Go goroutine-per-connection，后者天然适合 Agent 工具链并行
- **Python NLP 不可替代**：德语 NLP 的 Go 生态几乎为零，spaCy 依赖分析/形态学/POS 是核心竞争力
- **DAG 编排需求**：文章摄入 → NLP 分析 → CEFR 标注 → 练习生成 → FSRS 调度 → 输出，步骤间有依赖关系，适合 DAG 编排

---

## Considered Options

### Option 1: Go 做 HTTP 网关层（原始提案）

Go → HTTP 代理 → Python FastAPI。

- ❌ Python 已经是 async 框架，Go 在这里只是多一跳延迟
- ❌ 简历叙事：讲不清"为什么不能用 Python 做网关"
- ❌ 不产出有意义的 Go 工程经验

### Option 2: Go 做 Agent Runtime + 跨平台壳（采纳）

Go 编译为单二进制 CLI/桌面应用，内嵌 Agent DAG 编排逻辑，通过 subprocess（开发）/ HTTP localhost（分发）调用 Python NLP 引擎。

- ✅ 简历叙事："我设计并实现了一个多语言 Agent 编排引擎"
- ✅ Go 的 goroutine + channel 天然适配 DAG 步骤并行调度
- ✅ 跨平台分发从 PyInstaller 拼凑变为 go build 一事
- ✅ Python NLP 完整保留，零重写成本

### Option 3: 纯 Go 重写 NLP 层

用 Go prose 库重写 tokenization / POS / dependency parsing。

- ❌ 德语 NLP Go 生态几乎为零，工作量等同重写整个语言学层
- ❌ 质量不可能追上 spaCy（社区 10 年积累）

---

## Decision

**采纳 Option 2：Go Agent Runtime + Python NLP Engine 混合架构。**

### 架构拓扑

```
┌─────────────────────────────────────────────────┐
│  Go Binary (delector)                           │
│                                                 │
│  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ CLI / Desktop│  │ Agent Runtime            │ │
│  │ (跨平台壳)   │  │                          │ │
│  │              │  │  ┌─────────────────────┐ │ │
│  │  cobra cli   │  │  │ DAG Scheduler       │ │ │
│  │  wails/gio   │  │  │ (goroutine + chan)  │ │ │
│  └──────────────┘  │  └────────┬────────────┘ │ │
│                    │           │               │ │
│                    │  ┌────────▼────────────┐  │ │
│                    │  │ Tool Registry       │  │ │
│                    │  │                     │  │ │
│                    │  │  - ingest (HTTP→Py) │  │ │
│                    │  │  - analyze (sub)    │  │ │
│                    │  │  - writing_check    │  │ │
│                    │  │  - export (genanki) │  │ │
│                    │  │  - tts (edge-tts)   │  │ │
│                    │  └────────┬────────────┘  │ │
│                    └───────────┼───────────────┘ │
│                                │                 │
│  ┌─────────────────────────────▼───────────────┐ │
│  │ go-openai / DeepSeek API (LLM 调用层)       │ │
│  └─────────────────────────────────────────────┘ │
└────────────────────────┬────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          │ subprocess   │ HTTP localhost│
          │ (dev)        │ (dist)       │
          ▼              ▼              │
┌─────────────────────────────────────┐ │
│  Python NLP Engine (常驻进程)        │ │
│                                     │ │
│  FastAPI + spaCy + FSRS            │ │
│  de_core_news_md 模型              │ │
│  556 不规则动词词典                 │ │
│  五领域分析 + 句法树               │ │
└─────────────────────────────────────┘
```

> **工具清单注记（2026-09-06）**：Tool Registry 与 Python 侧 `delector/tools/__init__.py` 的 `TOOL_REGISTRY` 对齐，共 5 个工具：`ingest / analyze / writing_check / export / tts`。`exercise` 已更名 `writing_check`（见 ADR-0009）；原 `review` 工具 Python 侧尚不存在，Phase 2b+ 待 Python 侧新增工具后接入。

### 关键技术选型

| 组件                   | 选型                                             | 理由                                                        |
| ---------------------- | ------------------------------------------------ | ----------------------------------------------------------- |
| Agent Runtime          | go-openai + 自研 DAG scheduler                   | 固定工具链 DAG，不需要通用 Agent 框架；自研 ~800-1200 行 Go |
| Go↔Python 调用（开发） | subprocess + JSON stdin/stdout                   | 零依赖，进程隔离，调试简单                                  |
| Go↔Python 调用（分发） | HTTP localhost 微服务                            | Python 常驻进程复用 spaCy 模型，localhost 延迟可忽略        |
| LLM API                | go-openai-compatible（DeepSeek）                 | DeepSeek 走 OpenAI 兼容协议，复用成熟 SDK                   |
| 跨平台 CLI             | cobra                                            | Go CLI 标准选择                                             |
| 打包                   | Go 二进制 + Python venv 目录                     | 一个安装包，Go 管启动/调度，Python venv 管 NLP 运行时       |
| 测试                   | Go: testing + testify；Python: 现有 582 测试不动 | 两端独立测试，Python 基线零改动                             |

### DAG 编排示例

```go
// Agent 工具链 DAG：文章分析流程
dag := NewDAG("article-analysis")

dag.AddStep("ingest", ingestTool)        // RSS/文本 → 原文
dag.AddStep("nlp", nlpTool)              // spaCy 分析（依赖 ingest）
dag.AddStep("cefr", cefrTool)            // CEFR 标注（依赖 nlp）
// 注：CEFR 标注暂由 Python analyze 工具内部承担，独立 cefr 工具属 Phase 2b。
dag.AddStep("writing_check", writingCheckTool) // 练习生成（依赖 cefr）
dag.AddStep("tts", ttsTool)              // TTS 朗读（依赖 ingest，可与 nlp 并行）
dag.AddStep("export", ankiExportTool)     // Anki 导出（依赖 writing_check）

// Go runtime 自动并行无依赖步骤：
// ingest → [nlp, tts] 并行 → cefr → writing_check → export
result, err := dag.Run(ctx, article)
```

---

## Consequences

### 正面

1. **简历叙事清晰**："我用 Go 构建了一个 DAG-based Agent 编排引擎，调用 Python NLP 微服务"——不是翻译 CRUD，而是设计多语言系统
2. **Go 工程经验真实产出**：goroutine 调度、channel 数据流、context 超时控制、subprocess 管理、HTTP client/server、cobra CLI、单二进制打包——大厂 Go 后端面试的核心考点全覆盖
3. **Python 资产零损耗**：582 测试、spaCy 模型、556 动词词典、FSRS 算法全部保留
4. **跨平台分发质变**：从 PyInstaller 300MB+ 压缩到 Go 二进制 ~15MB + Python venv

### 风险与缓解

| 风险                                      | 缓解                                                                                                                    |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Python 子进程管理（僵尸进程、crash 恢复） | Go 端实现 heartbeat + 自动重启，subprocess 包装为 supervisor                                                            |
| 跨平台打包复杂度（Go + Python venv）      | 先做 Windows，macOS/Linux 跟进；用 GitHub Actions CI 自动化                                                             |
| 面试官追问"为什么不用纯 Go"               | 准备好论据：德语 NLP Go 生态为零，spaCy 10 年社区积累不可替代，混合架构是工业界常态（TensorFlow C++ core + Python API） |
| 开发效率下降（两个语言、两个构建系统）    | Python 端零改动（保持 FastAPI），只在 Go 端开发 Agent 层；用 HTTP 接口解耦，两端独立开发                                |

### 简历叙事模板

> **DeLector — Go Agent Runtime + Python NLP Engine 混合架构**
>
> - 设计并实现基于 DAG 的多语言 Agent 编排引擎（Go），用 goroutine + channel 实现工具链并行调度
> - Python NLP 微服务保留 spaCy 德语依赖分析、CEFR 标注、五领域拓扑分析等核心算力
> - Go↔Python 通信：开发阶段 subprocess+JSON，生产阶段 HTTP localhost 微服务
> - 跨平台分发：Go 单二进制 + Python venv 目录，替代原 PyInstaller 方案
> - 测试：Go 端 testify 单元测试 + Python 端 582 基线全绿

---

## Next Steps (Implementation Roadmap)

### Phase 1: Python 重构（前置，详见 [实施计划](../plans/2026-09-06-python-restructure-phase1.md)）

1. **T1** — 消除 Hazard：修 back-edge + 跨边界 import，创建 `utils.py`
2. **T2** — 数据层搬迁：8 个 `*_dict.py` → `delector/data/`
3. **T3** — NLP 层搬迁：`nlp.py` + `syntax_tree.py` + `linguistics.py` → `delector/nlp_engine/`
4. **T4** — 路由拆分：server.py 瘦身 → `delector/routes/` + app 工厂
5. **T5** — 服务层搬迁：writing/essay/exam/tts → `delector/services/`
6. **T6** — 基础设施搬迁：database/security/utils → `delector/core/`
7. **T7** — Agent 工具接口：`delector/tools/` 定义 Go 调用契约

### Phase 2: Go Agent Runtime

8. **T8** — Go 脚手架：cobra CLI + go.mod + 项目结构
9. **T9** — HTTP client 封装：调用 Python `POST /api/tools/{name}`
10. **T10** — DAG Scheduler：自研 ~800 行 Go（goroutine + channel）
11. **T11** — LLM 集成：go-openai-compatible 调 DeepSeek
12. **T12** — Tool Registry：5 个 Python tools 注册为 Go Agent tools
13. **T13** — Python 进程管理：supervisor（heartbeat + crash recovery）
14. **T14** — 跨平台打包：Go 二进制 + Python venv
15. **T15** — 集成测试：Go→Python 全链路
16. **T16** — 简历打磨：架构图 + design decisions + 性能对比
