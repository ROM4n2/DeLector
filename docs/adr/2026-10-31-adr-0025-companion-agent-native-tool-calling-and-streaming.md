# ADR-0025: 伴学 Agent 演进为原生 Tool Calling 与真流式双通道架构

- **状态**：ACCEPTED
- **日期**：2026-10-31
- **决策者**：席皓宇 (Haoyu Xi), Hermes Agent
- **关联 ADR**：
  - [[0023-interactive-layer-verification-driven-agent-loop]] (前序：验证驱动交互 Agent 闭环定案)
  - [[0010-encounter-zone-layered-go-agent-producer]] (伴学 Agent 协议中立性)
  - [[0009-python-package-restructure-deletion-test-and-tool-contract]] (工具契约)

---

## 1. 背景与问题陈述 (Context and Problem Statement)

在 ADR-0023 §10.4 中，系统因追求“与既有 `llm_client.chat` 返回 dict 同形”以及“测试 stub 极简”，采用了通过系统提示词强行约束模型输出单一 JSON 对象的方案：
`{"tool_call": ...}` 或 `{"thought": ..., "reply_de": ..., "reply_zh": ..., "proposal": ...}`。

在接入真实大模型（DeepSeek-V3 / DeepSeek-R1 / Qwen 等）的高强度实测中，该**“提示词语法解释器假说”（Prompt-as-Grammar Fallacy）**暴露出严重的工程缺陷：
1. **字符串转义冲突（Containeritis & JSON RFC 8259 崩溃）**：
   学习者答复需要丰富的 Markdown 排版（多行列表、物理换行、包含双引号的德语句子引述）。模型生成的物理换行符 `\n` (0x0A) 和引语直接导致 `json.loads` 抛出 `Invalid control character` 或 `Expecting ',' delimiter`。
2. **多轮少样本漂移（Few-Shot History Drift）**：
   在第二轮追问时，模型根据上一轮 Assistant 留下的纯文本解答，自然模仿输出纯 Markdown，文本中无外层 `{ ... }`，被系统一刀切判定为 `AI 服务返回内容非 JSON`。
3. **假流式超时假死（Blocking ReadTimeout）**：
   一次性要求模型完成“思考 + 语法分析 + 长篇排版 + 提炼卡片 + 闭合 JSON”，耗时常超 25 秒，导致 TCP 连接在空闲等待中被本地系统或网关掐断，伪装成 `AI 服务连接失败`。

---

## 2. 决策驱动力 (Decision Drivers)

- **终结格式脆弱性**：正文 Markdown 与系统结构化动作彻底物理隔离，杜绝 JSON 解析报错。
- **真正的 Agent 工具闭环**：以行业标准 `tools=[...]`（OpenAI / DeepSeek / Ollama 统一规范）驱动模型决策，而非提示词口头约束。
- **高频心跳与低延迟体验**：从第 1 秒起保持数据包流动，杜绝 `ReadTimeout` 断连。
- **向下契约兼容**：前端已成熟的纸质墨线折叠坞（Thought Accordion）、自适应打字队列（Adaptive Typewriter）与 HITL Proposal 契约保持稳定。

---

## 3. 备选方案权衡 (Considered Options)

### 方案 1：继续强化系统提示词与正则补丁（Discarded）
- **做法**：追加更多否定提示词（Negative Prompts），在后端写更多正则暴力提取。
- **放弃原因**：治标不治本。自回归模型的概率采样特性决定了提示词不能当作确定性的词法分析器，边缘长尾输入下依然会频繁漏网崩溃。

### 方案 2：原生 Tool Calling 单次阻塞版（Discarded）
- **做法**：引入 `tools` 参数，但依然等待全部生成后一次性返回。
- **放弃原因**：虽解决了 JSON 解析崩溃，但依然无法解决思考模型在生成长文本时的 25s+ 网络超时假死。

### 方案 3：Go Agent Runtime 统管原生 Tool Calling + 真流式双通道（Chosen Option）
- **做法**：
  - **由 Go Agent 模块（`agent/internal/companion`）作为伴学交互的统一编排中枢（Unified Agent Runtime）**：
    - 直接复用 Go 侧成熟的 `github.com/sashabaranov/go-openai`，获得天然的 `Tools`（原生 Function Calling）、`ReasoningContent`（DeepSeek-R1 原生思考链）与真流式 Token SSE 传输；
    - 彻底规避 Python 阻塞 25s 断连与 JSON RFC 8259 解析崩溃；
    - Go 侧调度工具时，通过既有的 `pythonsvc.Client.RunTool` 委托 Python 本地微服务（`analyze` / `writing_check` / `vocab_stats`）；
    - Go 侧常驻或提供独立服务，对外输出标准 SSE 事件流；FastAPI 路由网关透明反代。

---

## 4. 决策定案 (Decision Outcome)

选择 **方案 3 (Go 统管 Agent 编排方案)**。

### 核心规范定义
1. **Go 侧新增 `agent/internal/companion` 包**：
   - 定义原生 Tool Calling 规范（`analyze` / `writing_check` / `vocab_stats` / `propose_vocab_cards`）；
   - 基于 `go-openai.Client.CreateChatCompletionStream` 建立双通道：
     - 正文通道：纯 Markdown Token 直流推送到前端；
     - 思考通道：`ReasoningContent` 原生直推 Thought Accordion；
     - 工具/提议通道：原生 `ToolCalls` 调度 `pythonsvc.Client.RunTool` 并将 `Role: tool` 结果反馈回模型闭环。
2. **Go CLI 入口扩展 (`agent/cmd/delector`)**：
   - 暴露 `delector agent`（或在 `delector run` 内挂载伴学端口 8002），提供纯 Go 高并发 SSE 端点。
3. **Python 侧透明网关 (`delector/routes/companion.py`)**：
   - `/api/companion/chat` 向上探测 Go 伴学服务（默认 `http://127.0.0.1:8002`），以异步流式反代直接转发 SSE 帧，保持前端调用契约 100% 稳定不变；当 Go 伴学服务就绪时由 Go 完全接管，无缝切换。

---

## 5. 影响与后效 (Consequences & Trade-offs)

### 正向收益
- **彻底杜绝 JSON 崩溃**：学生面对的正式解答回归纯文本流动，格式错误率从 15% 彻底降为 0%。
- **连接抗脆弱性（Zero ReadTimeout）**：首 Token 1 秒内到达，持续的数据传输保持 TCP Socket 活跃。
- **真 Agent 自愈闭环**：模型可以连续自主调用多次工具，最终汇总给出详尽报告。

### 代价与守卫 (Guardrails)
- **单元测试 Stub 规范（Red Line）**：测试必须完全模拟 `stream` 迭代器和原生 `tool_calls` 字典，**严禁测试出网卡**。
- **状态机复杂度**：流式过程中需要对半成品 tool call chunks 进行累加组装（累加 `arguments` 碎片）。
