# Design Specification: 伴学智能体体系架构演进——会话持久化、学习画像深耕与运行时中间件 (Companion Harness Phase A & B)

**Date**: 2026-11-01  
**Status**: APPROVED (采纳 A->B 双阶段递进路线：先 A 业务持久化与画像深耕，后 B 运行时中间件重构)  
**Author**: DeLector Senior Systems Engineering Agent  
**Target Path**: `docs/specs/2026-11-01-companion-harness-persistence-and-middleware-design.md`  

---

## 1. Problem Statement & User Value

### 1.1 现状缺陷与技术痛点
1. **会话纯内存易失（Ephemeral State Trap）**：
   当前伴学抽屉的历史消息仅存留于前端 `companionState.messages` JavaScript 变量中。用户一旦刷新浏览器、切换文章或误触关闭，多轮语言学推导、生词建议与上下文全部丢失，无法形成持续学习沉淀。
2. **领域资产孤立与学习盲盒（Domain-Blindness）**：
   DeLector 拥有完备的 SQLite 离线资产（FSRS 间隔复习数据库、24 维德语语法图谱、万级考纲词库与动词配价），但 Go/Python 伴学 Agent 目前仅暴露通用的文本切分与基础词汇统计工具，无法感知当前学习者的实际记忆水平。导致模型提议生词卡时，经常提议用户早已掌握的词汇，或者因无法调阅权威本地双解而产生泛化的常识性解释。
3. **运行时状态机单体膨胀（Runtime Monolith Risk）**：
   `agent/internal/companion/loop.go` 承载了过多异构职责：OpenAI 流式事件读取、增量 Token 估算、60% 阈值压缩截断、Tool Calling 参数多轮拼接、Proposal ID 签发、空正文 Prompt Nudge 促动、SSE 响应输出全交织在单个 `Run()` 函数中，代码圈复杂度急剧升高，缺乏清晰的关卡拦截与可观测追踪。

### 1.2 用户价值与目标场景
- **用户画像**：备考 Goethe A2~B2 / TestDaF 的高强度精读者，需要将难句语法解构与长期生词闪卡记忆紧密结合。
- **核心场景 1（跨篇章连续答疑与复习）**：
  用户阅读《明镜周刊》或学术长文时向伴学发起长难句解析，关闭页面第二天重新打开该文章，抽屉能秒级恢复昨日的历史讨论、卡片提议记录与思维链要点。
- **核心场景 2（靶向智能制卡与已知词避让）**：
  伴学在解析长句拓扑后提议生词卡时，通过本地探针主动对比用户 FSRS 数据库：
  *已熟练掌握词（Stability 高、错次少）自动过滤*；
  *仅针对用户“未学过”或“近期复习遗忘率高”的核心考点词发起制卡提议*，大幅降低制卡噪音。
- **不做此项的代价**：
  伴学系统长期停留于“无状态玩具”，无法体现 DeLector 本地离线学习生态的独特优势，用户最终退化为使用通用 Web AI 聊天框。

---

## 2. User Journey & Core Flow

### 2.1 极简价值闭环 (Happy Path <= 3 步)
1. **唤醒与会话恢复 (Session Restore)**：
   用户打开阅读器并展开抽屉，系统自动关联 `(article_id, user_id)` 读取或激活最近一次会话 Thread，无缝展示上轮对话历史与历史提案卡片状态。
2. **学情感知与精准研读 (Personalized Linguistic Analysis)**：
   用户圈选复杂句点击提问，伴学调用 `get_learner_profile` 与 `query_dictionary`，结合用户当前 FSRS 词汇掌握率给出拓扑场切分，并在界面展示：“检测到您已掌握句中 9 个词，针对生疏的 2 个 B2 动介搭配已生成复习提案”。
3. **单点击穿与 FSRS 沉淀 (One-Click Ingestion)**：
   用户直接点击卡片上的【确认入库】，提案状态原地持久化为 `accepted`，卡片异步进入 SQLite 复习队列，完成闭环。

### 2.2 认知阻力与人机交互摩擦缓解 (Friction & Mitigation)
- **摩擦点 1**：如果每次进入都新建会话，文章阅读进度会杂乱无章；
  - **解法**：以当前文章 ID 作为默认上下文聚类键（Cluster Key），同一篇文章默认进入关联 Thread，同时提供【新对话】按钮以供清空重新开始。
- **摩擦点 2**：生词卡提议被用户驳回后，刷新页面又重复出现；
  - **解法**：Proposal 引入独立物理状态（`pending` / `accepted` / `rejected`），刷新后已确认卡片显示绿色徽标【已加入复习盒】，不再提供重复确认按钮。

---

## 3. Architecture & Data Models (Phase A & B 架构拓扑)

```
┌────────────────────────────────────────────────────────────────────────┐
│                   前端伴学抽屉 (Static ES Modules)                       │
│    cp-state.js  │  cp-api.js  │  cp-drawer.js (Typewriter + Thread UI) │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ SSE / HTTP REST
┌─────────────────────────────────▼──────────────────────────────────────┐
│                    Python FastAPI 网关 (端口 8000)                      │
│  - 路由: /api/companion/sessions, /messages, /proposal/execute          │
│  - SQLite WAL: companion_sessions, companion_messages, companion_props│
│  - 本地领域工具箱: get_learner_profile, query_dictionary, vocab_stats  │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ HTTP Forward (X-Session-ID, X-Effort)
┌─────────────────────────────────▼──────────────────────────────────────┐
│                  Go Agent Runtime 伴学引擎 (端口 8002)                 │
│  TurnPipeline (中间件架构):                                            │
│    [1. Context & Token Monitor] ──> 计算水位，触发 60% 动态压缩       │
│    [2. Domain Tool Invoker]     ──> 宽进严出入参转换，错误转回传       │
│    [3. State Machine Nudge]     ──> 空正文/提前结算强制拦截促动       │
│    [4. Event Bus Streamer]      ──> 结构化 SSE 输出与 JSONL 物理追踪    │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 数据库持久化模型 (SQLite WAL)

#### (1) `companion_sessions` (伴学交互会话表)
```sql
CREATE TABLE IF NOT EXISTS companion_sessions (
    id TEXT PRIMARY KEY,                   -- 格式: ses_<uuid4_hex>
    article_id TEXT,                       -- 关联文章ID（可为空，表示全局自由对话）
    title TEXT NOT NULL,                   -- 会话标题（缺省取用户首问前 20 字符）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_archived INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_companion_sessions_article ON companion_sessions(article_id, updated_at DESC);
```

#### (2) `companion_messages` (结构化会话消息与思维链表)
```sql
CREATE TABLE IF NOT EXISTS companion_messages (
    id TEXT PRIMARY KEY,                   -- 格式: msg_<uuid4_hex>
    session_id TEXT NOT NULL REFERENCES companion_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                    -- 'user' | 'assistant' | 'system' | 'tool'
    content TEXT NOT NULL,                 -- 正文内容（Markdown）
    thought TEXT DEFAULT '',               -- 深度思考过程（思考链正文）
    reasoning_effort TEXT DEFAULT 'medium',-- 'none' | 'low' | 'medium' | 'high'
    token_usage_json TEXT DEFAULT '{}',    -- {"prompt_tokens": N, "completion_tokens": N}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companion_messages_session ON companion_messages(session_id, created_at ASC);
```

#### (3) `companion_proposals` (结构化提议单项生命周期表)
```sql
CREATE TABLE IF NOT EXISTS companion_proposals (
    id TEXT PRIMARY KEY,                   -- 格式: prop_<timestamp_nano>
    session_id TEXT NOT NULL REFERENCES companion_sessions(id) ON DELETE CASCADE,
    message_id TEXT REFERENCES companion_messages(id) ON DELETE SET NULL,
    action TEXT NOT NULL,                  -- 'create_vocab_card' | 'create_cloze'
    title TEXT NOT NULL,                   -- 提议卡片标题
    payload_json TEXT NOT NULL,            -- 结构化载荷（单词、释义、例句等）
    status TEXT NOT NULL DEFAULT 'pending',-- 'pending' | 'accepted' | 'rejected'
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companion_proposals_session ON companion_proposals(session_id, status);
```

---

### 3.2 Phase A：领域原生工具扩展契约 (Domain-Native Tools)

在 `delector/tools/` 与 `agent/internal/companion/tools.go` 新增并对齐 2 大高价值领域工具：

#### 1. `get_learner_profile`
- **目的**：让 Agent 洞察当前用户的实际德语能力边界与记忆负荷。
- **输入参数**：
  ```json
  { "type": "object", "properties": { "include_weak_roots": { "type": "boolean", "default": true } } }
  ```
- **输出载荷**：
  ```json
  {
    "status": "ok",
    "total_known_words": 1420,
    "current_level_estimate": "B1",
    "fsrs_due_count": 18,
    "weakest_roots": ["seh", "fahr", "brech"],
    "recent_confused_pairs": [["kennen", "wissen"], ["fordern", "fördern"]]
  }
  ```

#### 2. `query_dictionary`
- **目的**：直接检索 DeLector 本地离线高信任度双解库，避免模型幻觉出不存在的德语搭配。
- **输入参数**：
  ```json
  { "type": "object", "properties": { "lemma": { "type": "string", "description": "德语单词原型" } }, "required": ["lemma"] }
  ```
- **输出载荷**：
  ```json
  {
    "status": "ok",
    "lemma": "anfallen",
    "pos": "verb",
    "valency": "vt. (hat angefallen) 袭击; vi. (ist angefallen) 发生/产生",
    "cefr": "B2",
    "collocations": ["Kosten fallen an", "Zinsen fallen an"],
    "definitions_zh": ["产生，发生（费用等）", "袭击，攻击"]
  }
  ```

#### 3. 增强 `propose_vocab_cards`
- 工具执行时，底层自动比对当前用户的 `get_known_vocab_set()`，对用户掌握度高于 0.8 的词执行自动跳过，并在返回摘要中注明：`已剔除 3 个已知词，提议 2 个生词`。

---

### 3.3 Phase B：Go Runtime 管道中间件解耦 (TurnPipeline)

将 `agent/internal/companion/loop.go` 的单体执行流解耦为中间件调用链：

```go
// agent/internal/companion/pipeline.go

type TurnContext struct {
    SessionID       string
    Turn            int
    MaxTurns        int
    Messages        []openai.ChatCompletionMessage
    ActiveContext   string
    ReasoningEffort string
    HadToolExecution bool
    FullContent     *strings.Builder
    EventsChan      chan<- Event
    CancelCtx       context.Context
}

type TurnMiddleware func(ctx *TurnContext, next func() error) error

// 核心中间件链：
// 1. ContextGuardMiddleware: 动态检测当前 token 容量，超出 contextWindow * 0.6 时平滑折叠旧轮次
// 2. StreamDispatchMiddleware: 负责与 LLM 上游建联并驱动 chunk 流
// 3. ToolExecutionMiddleware: 识别 tool_calls，调用 Python REST 端点，收集并构造 ToolResultMessage
// 4. PromptNudgeMiddleware: 当且仅当 hadToolExecution == true 且当前轮次未产出实质正文时注入强力促动
// 5. TraceLoggingMiddleware: 记录每轮毫秒耗时与 Token 使用量并写盘
```

---

## 4. Edge Cases & Resilience (边界与韧性)

1. **跨文章会话切换碰撞（Session Race）**：
   用户在不同 Tab 打开了两篇不同文章并同时呼出伴学抽屉。
   - **防御机制**：前端每个伴学请求严格带上 `X-Session-ID`。后端以 Session ID 为隔离单元，读写事务采用 SQLite WAL 模式，确保不同文章的伴学会话绝对独立，互不污染。
2. **离线与轻量环境降级（Zero Go Runtime Fallback）**：
   在 Android Chaquopy 或未安装 Go 二进制的环境中运行。
   - **防御机制**：FastAPI 后端在 `delector/routes/companion.py` 保持透明降级。若 8002 端口探测失败，自动路由至 Python 内置的轻量伴学服务（单轮补全 + 本地字典直接直出），确保无 Go 环境下核心教学体验依然可用。
3. **提案确认重放与失效（Proposal Idempotency）**：
   用户网络抖动下对同一个生词卡连续点击多次【加入复习】。
   - **防御机制**：`companion_proposals` 表以 `id` 为主键，后端 `execute_proposal` 执行时采用原子更新 `UPDATE companion_proposals SET status = 'accepted' WHERE id = ? AND status = 'pending'`。影响行数为 0 时幂等返回成功，杜绝在 FSRS 中重复创建多张同名卡。

---

## 5. Test Strategy (测试策略与确定性信号)

### 5.1 自动化测试矩阵
1. **单元测试 (Unit Suite)**：
   - `tests/test_companion_sessions.py`：测试会话创建、恢复、消息追加与级联删除；
   - `tests/test_companion_domain_tools.py`：测试 `get_learner_profile`、`query_dictionary` 及 `propose_vocab_cards` 已知词过滤逻辑；
   - `agent/internal/companion/pipeline_test.go`：使用 `httptest.Server` 模拟中间件管道的 6 轮流转、Prompt Nudge 注入与 60% 上下文压缩。
2. **端到端契约测试 (Contract Gate)**：
   - 运行四道机械门禁，扩展 `tools/check_companion_contract.py` 覆盖新的持久化路由（`/api/companion/sessions`）与工具字段一致性。

### 5.2 物理验证命令清单 (Physical Receipts)
```bash
# 1. 验证 Python 伴学会话持久化与新领域工具测试
python3 -m pytest tests/test_companion_sessions.py tests/test_companion_domain_tools.py -v

# 2. 验证 Go 伴学中间件管线逻辑与单测
cd agent && go test -v -run TestTurnPipeline ./internal/companion/...

# 3. 运行前端与伴学契约机械门禁
cd .. && python3 tools/check_frontend_layers.py && python3 tools/check_companion_contract.py
```

---

## 6. Fog of War & Scope Boundaries (迷雾与边界)

### 6.1 Fog of War (待进一步实测的技术未知点)
1. **本地字典查询时延**：当难句涉及 5 个以上生词且同时发起本地词典检索时，SQLite 并发读查询对整体首字生成时延（TTFT）的影响，需在实施中加入毫秒级耗时监控。
2. **FSRS 掌握度阈值调优**：将“用户已掌握词”的 Stability 阈值定在何处（如 S > 21 天 还是 S > 30 天）能够达到最佳推荐体验，需在完成 A 阶段后结合实测样本调参。

### 6.2 Out of Scope (明确不纳入本次范围)
1. **跨设备云端会话漫游**：本次会话持久化严格局限在本地 SQLite 数据库中，不涉及跨机 WebRTC / 云同步同步链路（仍走现有的局域网 6 位码手动导出方案）。
2. **复杂多 Agent 树状派发 (Multi-Agent Swarm)**：伴学系统维持“单一主持人 Agent + 多本地确定性工具”的拓扑，坚决不引入由模型自主生成的嵌套子 Agent，杜绝死锁与 Token 膨胀。

---

## Self-Review Checklist
- [x] Zero unpopulated placeholders.
- [x] No ambiguous assumptions or hidden scope creep (明确分划 Phase A 业务持久化与 Phase B 中间件重构).
- [x] The Ladder of Reuse checked: 严格复用现有 SQLite WAL 引擎与 FSRS 状态表，拒绝引入新的数据库依赖。