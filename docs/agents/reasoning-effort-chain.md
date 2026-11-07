# 思考强度（reasoning effort）链路与上游契约

> 记录日期：2026-11-07。本文是「设置页四档 → 真实请求体 → 上游响应差异」的取证与实现说明，
> 供后续排查/复核直接引用。**先看 §1 的结论与证据等级，别再把文档推断当成已验证事实。**

## 1. 结论先行

### 1.1 上游到底支持什么

依据 **DeepSeek 官方 API 文档（2026-11-07 抓取，见 §4）**，Chat Completions 请求体支持：

| 字段 | 取值 | 语义 |
| --- | --- | --- |
| `reasoning_effort` | `none` / `low` / `high` / `max` | `none` 关闭思考；其余开启且强度递增 |
| `thinking` | `{"type": "enabled"}` / `{"type": "disabled"}` | 思考模式开关；与 `reasoning_effort` 同时出现时以开关为准 |
| `max_tokens` | 上游默认（不传） | 输出上限（含思维链占用）。本项目**不设**：由上游按模型/思考预算决定，硬编码会截断 |

上游对 effort 的映射表（官方原文）：

| 请求传入 | 实际生效 |
| --- | --- |
| `minimal` | `low` |
| `low` | `low` |
| `medium` | `high` |
| `high` | `high` |
| `xhigh` | `high` |
| `max` | `max` |
| `ultra` | `max` |

其它与思考模式相关的真实约束：

- 思考模式下 `temperature` / `presence_penalty` / `frequency_penalty` **不生效**（不报错）；
- `top_p` 仅在 `deepseek-flash` 的思考模式下生效，有效区间 `0.95`–`1.0`；
- 响应消息里思维链在 `reasoning_content` 字段，与 `content` 并列；
- 模型名：`deepseek-flash` 是当前正式名（官方注明由 DeepSeek-V4.1-Flash-1017 提供），
  `deepseek-v4-flash` 是遗留别名。**之前评审文档里「v4 才是正式名」的判断是错的，已按本记录纠正。**

### 1.2 证据等级（哪一步已验证、哪一步是推断）

| 事项 | 等级 | 说明 |
| --- | --- | --- |
| 本地 `deepseek-flash` 能跑通 | **用户实测事实** | 用户明确纠正：实际使用中就是 `deepseek-flash`，本文不改模型名 |
| 参数取值/映射表/`reasoning_content` | **官方文档** | 2026-11-07 抓取官方 Chat Completions 与思考模式文档 |
| 参数是否被上游接受、四档响应是否真有差异 | **未验证（缺有效 key）** | 本地 4 份 `.env` 的 key 对 `api.deepseek.com` 全部返回 `401`，实测记录见 §5 |
| 设置 → Python/Go 请求体 | **已验证** | 单测 + 结构守卫 + 具名变异，见 §3 |

> 因此本次交付的是「链路正确 + 映射有文档依据」，**不是**「四档响应差异已被真实请求证明」。
> 拿到有效 key 后运行 `tools/probe_reasoning_effort.py` 即可补齐最后一项，脚本见 §5。

## 2. 链路取证（改前 → 改后）

### 2.1 改前：四档只落在设置页，没进请求体

- 设置页控件与持久化：`static/modals/settings_modal.html`（`#set-reasoning-effort`）→
  `static/js/main.js` → `POST /api/settings` → `delector/core/db/settings.py`。
- 伴学侧只是把值塞进 `options.reasoning_effort`（`static/js/cp-api.js`），
  但 Python 路由 `delector/routes/companion.py` 的 `CompanionChatReq` **没有该字段**，
  `dispatch_companion_stream` 的 `req_payload` 也只有 `messages/context` ⇒ 值被丢弃。
- Go Agent 虽然从 body/header 读了 `reasoning_effort`（`agent/internal/companion/server.go`），
  但只写进 trace（`pipeline.go`），`loop.go` 的 `streamReq` 从未带上该字段。
- 四条 Python 生成路径（释义/语法/笔记/润色）调用 `llm_client.chat` 时也没有任何思考参数。

结论：**改前是「界面显示某档、请求里根本没有」的说谎状态。**

### 2.2 改后：单一映射出口，三端同构

设置页档位 → 上游取值（Python `llm_client.map_reasoning_effort` 与 Go
`companion.MapReasoningEffort` 必须一致）：

| 设置页 | 上游 `reasoning_effort` |
| --- | --- |
| 关闭 `none` | `none` |
| 极速 `low` | `low` |
| 平衡 `medium` | `high` |
| 深度 `high` | `max` |

为什么不是原样透传：上游会把 `medium` 吃掉成 `high`，与「深度」同档 ⇒ 四档不可区分。
显式映射后四档对应 `none/low/high/max` 四个不同上游取值。

链路落点：

- Python 生成路径：`llm_client.chat(..., reasoning_effort=get_effective_reasoning_effort())`
  - `delector/routes/main.py`（释义、语法）
  - `delector/routes/articles.py`（笔记辅助）
  - `delector/routes/writing.py`（润色）
  - `delector/routes/settings.py`（连通性自检固定 `none`，避免 5 个 token 全耗在思维链）
- 伴学：`cp-api.js` 的 body/header → `routes/companion.py` → `dispatch_companion_stream`
  → Go（`req_payload.reasoning_effort` + `X-Reasoning-Effort`）或 Python 回退内核
  → `llm_client.chat`。
- Go：`loop.go` 在 `RunLoop` 入口归一化（请求显式值 > Agent 缺省值），trace 与真实
  `streamReq` 使用同一个「实际发出」的值；本地 Ollama 回退通道会清空该字段（不认）。

## 3. 验证与守卫

已执行（worktree `D:\Code\DeLector-thinking`，分支 `feat/reasoning-effort-wiring`）：

```powershell
# Python
D:\Code\DeLector\.venv\Scripts\python.exe -m pytest `
  tests/test_llm_client.py tests/test_companion_provider_integration.py `
  tests/test_companion_routes.py tests/test_companion_services.py `
  tests/test_companion_agent_loop.py tests/test_companion_api_contract.py -q
# 111 passed

# Go
cd agent; go test ./internal/companion/... ./cmd/...
# ok
```

具名变异（每条都被对应测试捕获，改后已还原）：

| # | 变异 | 捕获测试 |
| --- | --- | --- |
| 1 | Python 映射把 `high` 改成 `high` | `test_reasoning_effort_maps_tiers_to_distinct_upstream_values` 等 3 条 |
| 2 | `articles.py` 调用点漏传 `reasoning_effort` | `test_all_llm_call_sites_forward_reasoning_effort` |
| 3 | `dispatch` 的 `req_payload` 漏发字段 | 伴学转发 2 条（KeyError） |
| 4 | Go 映射把 `high` 改成 `high` | `TestMapReasoningEffort` + `TestRunLoopSendsEffectiveReasoningEffort` |
| 5 | Go `streamReq` 漏带字段 | `TestRunLoopSendsEffectiveReasoningEffort` 全部子用例 |
| 6 | `llm_client.chat` 不合并 payload | `test_chat_payload_carries_mapped_reasoning_effort` 四档 |

## 4. 官方文档来源

- 思考模式：<https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/>
- Chat Completions API：<https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/>
- 首次调用（模型名说明）：<https://api-docs.deepseek.com/>

## 5. 真实请求验证（待有效 key）

`tools/probe_reasoning_effort.py` 会用当前设置里的 key/base/model 依次发四档请求，打印
`reasoning_content` 长度、耗时、`usage`。当前本地 key 已失效（四份 `.env` 均 401），
运行会直接给出 401 提示；换成有效 key 后：

```powershell
D:\Code\DeLector\.venv\Scripts\python.exe tools\probe_reasoning_effort.py
```

预期（文档推断，待实测确认）：`none` 无 `reasoning_content`；`low < high < max` 的
思维链长度/耗时/token 数单调上升。

2026-11-07 本地实测（key 已失效，仅证明链路与鉴权失败路径）：

```text
base_url=https://api.deepseek.com model=deepseek-v4-flash 当前档位=medium
none   -> none | HTTP 401 | 1.44s | Authentication Fails, Your api key: ****802c is invalid
low    -> low  | HTTP 401 | 1.30s | ...
medium -> high | HTTP 401 | 1.39s | ...
high   -> max  | HTTP 401 | 1.23s | ...
```

四档请求确实带着不同的 `reasoning_effort` 发出去了（`none/low/high/max`），但上游因 key
失效未进入参数校验阶段 ⇒ **不能据此声称参数被接受**。

## 6. 已知风险与边界

- **请求体不设 `max_tokens`**：输出预算交给上游默认值，代码里不再保留 per-call 硬编码
  （原 `DEFAULT_MAX_TOKENS = 4096` / 连通性 5 / 探针 4096 均已删除）。理由：思考 token
  与正文共享输出预算，固定值在上下文窗口或思考预算不同的模型上会提前截断；上游默认值
  会随模型演进变化，**不得用「窗口多大」的假设去推算上限**。
- 循环级 `max_tokens_total`（`polish_loop` 4096 / `companion_agent` 8192）保留：它们
  **不进入请求体**，只在多轮之间累计 completion 做成本刹车；单轮输出不受其限制。
- 实验 harness `tools/bench_judge_gaming.py` 刻意不传 `reasoning_effort`：它要钉
  `temperature`，而思考模式会忽略 `temperature`，混入会破坏基准语义。
- 本轮不改设置 UI（另一条线在做设置信息架构），只保证参数链路不说谎。
- 未触碰 `static/`、`style.css`、ADR-0029/0030、`android/`。
