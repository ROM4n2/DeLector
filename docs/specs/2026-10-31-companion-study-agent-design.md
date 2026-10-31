# 内置伴学宠物智能体化（Companion Study Agent）· 设计稿

> **性质**：设计稿（`docs/specs/`），不是实施计划。实施前需另立 `docs/plans/` 计划。  
> **状态**：APPROVED（2026-10-31，用户拍板采纳「以 B 态验证驱动伴学为当前过渡抓手，以协议中立与契约解耦直通长期 C 态」演进路线）。  
> **实施计划**：待立案（`docs/plans/archive/2026-10-31-companion-study-agent.md`）。  
> **上游约束**：  
> - ADR-0008（Go Agent Runtime + Python NLP Engine 混合架构全景）  
> - ADR-0010 §5（交互请求不加 Go 代理跳，交互层留 Python）  
> - ADR-0021（主体语言继续保持 Python，交付与运行时为第一判据）  
> - ADR-0023（验证驱动 Agent 循环、有界、确定性裁判独立终审、拒绝自我安慰）  
> - `docs/design-system.md`（去 AI 同质化，德式印刷墨线、真实纸质与学术排版）  
> **基线**：v5.19.0 @ `master`（全量 2584 passed + 2 skipped，六道机械闸全绿）。

---

## 0. 结论先行与演进定位

**以「验证驱动的导学 Agent（方案 B）」为当下唯一交付面，坚决不越级直接实现长程工作流（方案 C）；但全面强制「协议中立」与「工具契约解耦」，作为未来 Go 常驻 Supervisor 接管的绞杀者第一阶段（Phase 1 Strangler）。**

三项关键架构决断（防止后续开发偏航）：

| 决断项 | 采纳结论 | 否决方案 | 核心依据 |
| :--- | :--- | :--- | :--- |
| **交互载体** | **伴学抽屉（Companion Drawer）** | 全局居中聊天大弹窗 / 浮动药丸输入框 | 遵循 `docs/design-system.md` 去 AI 同质化；精读与答题上下文不应被阻断遮挡。 |
| **执行权限** | **写操作严格 HITL 提议制（Proposal）** | Agent 自主静默写库 | 数据库属于高信任区，杜绝 Agent 幻觉污染用户的 FSRS 卡盒与学习进度。 |
| **运行时宿主** | **Python 异步单体（FastAPI + SSE）** | 直接启动 Go 常驻长程 DAG | 严格遵守 ADR-0010 §5「交互请求不加 Go 代理跳」红线，杜绝跨进程 IPC 延迟与复杂度。 |

---

## 1. 问题陈述与用户价值 (Problem Statement & User Value)

### 1.1 现状与实测基线
1. **现存宠物是纯展示玩具 (`static/js/companion.js` · 782 行)**：
   - 依赖本地预置德语模板 `PHRASES`，仅在制卡、完形得分、连续打卡等离散事件发生后弹出 2~4 秒气泡，缺乏主动感知与深层交互能力。
2. **交互层 Agent 算力零碎但基础扎实**：
   - 仓内已存在 `delector/routes/tools.py` 暴露的 6 大确定性工具（`ingest / analyze / writing_check / export / tts / vocab_stats`）。
   - ADR-0023 已在 `delector/services/polish_loop.py` 验证了「模型决策工具调用 + JSON 契约 + 轮次/Token 硬预算 + 确定性裁判终审」闭环的有效性。
3. **痛点与不做代价**：
   - **痛点**：用户在阅读德语复杂长难句或备考写作时，现存 UI 只能给出机械的语法树/词性标注，无法就「该从句在语用上的褒贬倾向」、「某近义词在本文语境下的细微区别」等深层疑惑发起即时追问与学情诊断。
   - **不做的代价**：宠物系统沦为可有可无的装饰品；用户在遇到规则引擎边界外的语言学困惑时，只能切出应用使用通用大模型，上下文丢失且无法与本地生词本、复习流打通。

### 1.2 目标场景与用户画像
- **目标用户**：备考 Goethe A1~B2 / TestDaF 的德语学习者，具备自主精读与做题意愿。
- **高频场景**：
  1. **语境深度诊断**：用户在阅读界面圈选难句，点击伴学宠物，一键获得结合了上下文语法拓扑与文化背景的深度剖析。
  2. **学情驱动的靶向提优**：宠物检测到用户在生词复习或完形填空中高频出错（如某类格变化失误），主动发起互动，生成 3 道定制化微诊断题。
  3. **受控的批量转化**：用户请求「将本文出现的 4 个 B1 动介搭配提取并做成闪卡」，Agent 筛选后以卡片形式提交确认，用户单点确认入库。

---

## 2. 用户旅程与核心流程 (User Journey & Core Flow)

### 2.1 极简闭环（≤3 步达成交付）
```
[步骤 1: 触发] ──> 用户选中文本或点击常驻悬浮宠物（Eule）
                 │  系统响应：宠物播放轻量倾斜动画，右下角平滑展开伴学抽屉（Drawer）
                 │  自动注入当前视口元数据（选中文本、文章标题、当前阅读段落）
                 ▼
[步骤 2: 交互] ──> 用户点击预设伴学动作（如「深挖语用」、「语法问诊」）或自由输入提问
                 │  系统响应：抽屉内以 SSE 流式输出思考过程与工具调用进度标签
                 ▼
[步骤 3: 交付] ──> Agent 交付结构化解答；若涉及写操作，输出确认卡片（Proposal Card）
                 │  用户点击「确认加入卡盒」-> 调用本地原子 API -> 宠物跳跃庆祝闭环
```

### 2.2 认知摩擦与消解策略
- **摩擦点 1：打断阅读心流**。
  - *消解*：抽屉采用右侧窄版停靠（Docked Side Drawer），在桌面端仅占据 `360px` 宽度，左侧文章正文自动收缩边距而不遮挡；在移动端（≤768px）自底向上弹出，并提供一键滑落手势。
- **摩擦点 2：黑盒等待焦虑**。
  - *消解*：禁止全文本生成完毕后再返回；必须通过 SSE 实时展示状态切片（如 `[正在检索语法拓扑...]`、`[正在核对 B1 词表覆盖率...]`），反馈延迟控制在 `<300ms` 内。
- **摩擦点 3：AI 幻觉制卡污染**。
  - *消解*：禁止 Agent 直接执行数据库写操作；必须通过 `proposal` 呈现卡片预览（含正反面、例句、语法标签），由用户点击原生按钮提交。

### 2.3 异常反馈与降级恢复
- **未配置 API Key / 离线环境**：抽屉提示「当前处于离线模式，Agent 深度问诊不可用」，并平滑降级为现存的纯本地短语与发音辅助，不报 500。
- **上游 LLM 超时或额度耗尽**：流式推送带有人话原因码的错误卡片（如 `[上游响应超时，请重试]` 或 `[超出单次对话预算]`），保留用户已输入内容，提供一键重试按钮。

---

## 3. 架构设计与契约模型 (Architecture & Data Models)

### 3.1 系统拓扑与职责边界

```
┌─────────────────────────────────────────────────────────────┐
│ 前端界面层 (Vanilla JS ES Modules - 遵循去 AI 同质化规范)       │
│                                                             │
│   static/js/companion.js (门面分发、SVG 动画、日常激励)       │
│             │                                               │
│             ├──> static/js/cp-state.js  (纯状态容器)         │
│             ├──> static/js/cp-drawer.js (抽屉渲染与交互卡片)  │
│             └──> static/js/cp-api.js    (SSE 流解析与 HTTP) │
└──────────────────────────────┬──────────────────────────────┘
                               │ SSE / POST (HTTP 本地回环)
┌──────────────────────────────▼──────────────────────────────┐
│ 后端交互层 (FastAPI - delector/routes/companion.py)          │
│                                                             │
│   - POST /api/companion/chat (SSE 流式会话入口)              │
│   - POST /api/companion/proposal/execute (受限写操作执行)    │
│   - GET  /api/companion/context (快速提取当前学情摘要)       │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ 导学 Agent 内核 (delector/services/companion_agent.py)       │
│                                                             │
│   - Multi-Turn Loop (MAX_TURNS=3, DEADLINE=15s)             │
│   - Model Tool Invocation (JSON {"tool_call": ...})         │
│   - Tool Whitelist Execution (只读/诊断型)                   │
│   - Deterministic Judge (spaCy / 规则校验结果兜底)          │
└──────────────┬──────────────────────────────┬───────────────┘
               │ 内部调用                      │ 异步 HTTP
┌──────────────▼──────────────┐┌──────────────▼───────────────┐
│ 工具接口层 (delector/tools)  ││ LLM Client (DeepSeek / API)   │
│ - analyze (句法依存)        ││ delector/services/llm_client │
│ - writing_check (规则裁判)  │└──────────────────────────────┘
│ - vocab_stats (词汇统计)     │
└─────────────────────────────┘
```

### 3.2 模块解耦与前端状态机 (`cp-state.js`)
为防止 `companion.js` 膨胀为巨型单体，严格执行前端解耦：
1. **`companion.js`**：保持为总控入口，负责 SVG 渲染、呼吸与表情控制、全局事件监听（制卡、打卡）。
2. **`cp-state.js`**：抽屉状态管理。维护当前 `isOpen`、`sessionMessages`、`currentStreamStatus`、`activeProposals`。
3. **`cp-drawer.js`**：纯 DOM 视图层。负责渲染墨线风格的会话气泡、Markdown 轻量解析、工具进度 Chips 以及 Proposal 确认卡片。
4. **`cp-api.js`**：协议封装。使用 `fetch` + `ReadableStream` 读取后端 SSE，分发强类型事件。

### 3.3 中立 SSE 协议契约 (Protocol-Neutral SSE Events)
后端统一以 `text/event-stream` 格式推送，每行遵循标准 `event: <name>\ndata: <json>\n\n` 规范。此协议面向未来 Go Supervisor 保持完全中立：

| Event Name | Data Payload Schema | 业务语义 |
| :--- | :--- | :--- |
| `thought` | `{"text": "string"}` | 模型内部链式思考片段（折叠弱化展示） |
| `delta` | `{"text": "string"}` | 交付给用户的正文流式增量 Markdown |
| `tool_start`| `{"tool": "string", "label": "string"}` | 工具开始调用，通知前端亮起状态 Chip |
| `tool_end` | `{"tool": "string", "summary": "string"}`| 工具调用完成，展示确定性执行摘要 |
| `proposal` | `{"id": "string", "action": "string", "title": "string", "payload": object}` | 写操作提议（生成确认卡片，待用户确认）|
| `done` | `{"turns": int, "tokens": int, "reason": "ok\|budget_exceeded\|deadline"}` | 正常收敛结束标志 |
| `error` | `{"code": "string", "message_zh": "string"}` | 发生非预期异常，结束流并展示人话原因 |

### 3.4 提议模式与写操作执行契约 (Proposal Pattern)
当用户要求「帮我把这段话做成生词卡」时，Agent 循环不得直接 `INSERT INTO cards`，必须返回提议事件：
```json
{
  "id": "prop_20261031_001",
  "action": "create_vocab_cards",
  "title": "生成 3 张生词复习卡",
  "payload": {
    "cards": [
      {
        "word": "die Herausforderung",
        "reading": "挑战",
        "context_sentence": "Das ist eine große Herausforderung.",
        "level": "B1"
      }
    ]
  }
}
```
前端收到后渲染为带「确认添加」与「放弃」按钮的德式卡片。点击「确认」后，前端直接调用现存已受检的本地端点 `POST /api/cards/vocab`，确保写操作权限与验证逻辑完全复用既有安全面。

---

## 4. 边界情况与弹性防御 (Edge Cases & Resilience)

### 4.1 网络抖动与连接中断
- **单请求串行护栏**：每个前端标签页同一时间仅允许一个在途的 Companion Agent 会话流。在旧请求未完成时，新输入按钮置灰；用户强制发起新提问时，前端主动调用 `AbortController.abort()` 掐断旧连接。
- **服务端主动收尸**：后端检测到客户端断开连接（`request.is_disconnected()`）时，立即通过 `asyncio.CancelledError` 终止后续模型生成与工具调用，严禁后台无主空转消耗 Token。

### 4.2 预算与死锁防御
- **硬时间闸门**：单次伴学请求的总耗时上限锚定为 `15.0s`（严格小于前端全局超时 `25.0s`）。耗尽时内核带 `reason="deadline"` 优雅退出，返回已生成的有效文本，不抛裸 504。
- **Token 消耗上界**：单次会话循环严格限制 `MAX_TURNS = 3`，总 Completion Token 上限锁死为 `2048`（按 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 实测折算或真实 API 信封取值），杜绝死循环递归。

### 4.3 离线与降级防御
- **配置探测**：在请求入口快速校验 `API_KEY` 是否有效。未配置时立即在 SSE 首包下发降级通知，前端自动切换为「伴学助手（离线模板模式）」，从本地词表与静态规则库中调取匹配内容。

---

## 5. 测试策略与验证命令 (Test Strategy)

根据项目「零测试假绿（Zero Dead-Green）」与「必须带物理证据」的工程红线，制定三层测试体系：

### 5.1 单元测试（离线纯 Python，零依赖真 Key）
- **`tests/test_companion_agent_loop.py`**：
  - 测试循环的有界性：注入恒返回 `tool_call` 的 mock 模型，验证其在达到 3 轮后强制以 `budget_exceeded` 收敛，不得挂死。
  - 测试裁判终审：验证模型生成的释义在通过 `analyze` 工具核验失败后，能够触发回炉重试。
  - 测试提议契约：验证写操作不会触发真实 DB 写入，仅输出合法的 `Proposal` 结构。

### 5.2 端点与 SSE 契约测试
- **`tests/test_companion_routes.py`**：
  - 使用 FastAPI `TestClient` 测试 `/api/companion/chat`，解析完整的 `text/event-stream` 数据行，断言首包时间与事件类型的严谨性。
  - 验证 `_require_localhost` 权限控制：模拟非 127.0.0.1 访问时严格返回 403。

### 5.3 前端契约与状态机守卫
- **`tools/check_companion_contract.mjs`**：
  - 新增专用探针，静态提取 `cp-api.js` 支持的 SSE 事件类型，与后端 `companion_agent.py` 发出的事件常量字典进行双向配对断言，漂移即报警。

### 5.4 验证命令清单
```bash
# 1. 运行伴学智能体专用单元测试
PYTHONIOENCODING=utf-8 pytest tests/test_companion_agent_loop.py tests/test_companion_routes.py -v

# 2. 静态类型与规范检查
ruff check delector/routes/companion.py delector/services/companion_agent.py
mypy --strict delector/routes/companion.py delector/services/companion_agent.py

# 3. 前端契约与机械闸
node tools/check_companion_contract.mjs
node tools/check_frontend_layers.mjs
```

---

## 6. 战争迷雾与明确非目标 (Fog of War & Scope Boundaries)

### 6.1 战争迷雾与裁定 (Fog of War - Resolved)
1. **模型输出的流式体验与工具调用的冲突**：
   - *裁定*：在模型发起 `tool_call` 的轮次，前端仅流式显示其思考/状态碎片；当工具返回且最终生成自然语言时，再全速推流回复文本。
2. **移动端触控冲突**：
   - *裁定*：在视口宽度 ≤768px 时，悬浮宠物收缩为底部状态胶囊，抽屉以半屏 Bottom Sheet 展现，避免遮挡精读交互高频区。

### 6.2 显式非目标 (Explicit Non-Goals - 本阶段坚决不做)
1. **坚决不做 Go 进程长程 DAG 调度**：本期不改动 `agent/` 目录下的 Go 批处理逻辑，所有交互限定在 Python FastAPI 内存会话内完成。
2. **坚决不做自动执行的静默数据库写入**：任何卡片新增、进度重置、文章删除等操作，必须经由 Proposal 由人类点击确认。
3. **坚决不做实时全双工语音对讲 (Voice Duplex)**：语音能力继续严格复用既有单向德语 TTS（`player.js`），不引入 STT/麦克风实时监听流。
4. **坚决不做三方通用重型 Agent 框架集成**：严禁引入 LangChain / LangGraph / Semantic Kernel 等依赖，代码必须使用纯原生异步协程实现。

---

## 7. 自检核对清单 (Self-Review Checklist)

- [x] **零占位符**：全文无任何 `TODO`、`TBD` 或模糊指代，所有类型、路径与常量均明确落地。
- [x] **无隐式范围膨胀**：严格切分为当前可交付的导学抽屉形态，不偷跑长程批处理引擎。
- [x] **阶梯复用优先**：全面复用现有 `delector/tools/` 6 大工具与 `polish_loop.py` 经受检验的循环预算机制。
- [x] **红线完全合规**：遵循 ADR-0010 §5（交互不加 Go 代理跳）、ADR-0023（三要素有界 Agent 循环）与去 AI 同质化设计系统规范。