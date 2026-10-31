---
title: "ADR-0023: 交互层引入「验证驱动 agent 循环」——不换主体语言，用确定性裁判换取 agent 语义"
created: 2026-10-14
updated: 2026-10-15
type: project
tags:
  - project/delector
  - topic/architecture
  - topic/agent
  - topic/llm
  - topic/testing
status: accepted
audience:
  - architect
  - agent
source: "用户提案「不换主体语言，能不能加入agent元素？」+ 会话实测（5 处 LLM 调用点物理读取 + Go 集成门禁真跑取红卡）+ 2026-10-14 `/dfs-grill` Track 2 双镜审讯（product-ux + sre-resilience 席位，逐条对表库内 `01-Rules/AGENT-SDK-PATTERNS` 的 Pi 模式与 `02-Distilled/AGENT-GOVERNANCE-SECURITY`）+ 用户拍板（Q1-B / Q2-A / Q3-A / Q4-A）"
authority: synthetic
claim_risk: medium
review_status: unreviewed
---

# ADR-0023: 交互层引入「验证驱动 agent 循环」

> **状态说明**：`status: accepted`（2026-10-14 经 `/dfs-grill` Track 2 双镜审讯定稿）—— 方向与实现形态均已拍板。审讯修正了原提案的三处关键设计（**流转改由模型驱动**、**工具面收窄为任务级白名单**、**收尾必须过裁判终审**）。正文 §1~§7 保留提案时的原始表述作为记录，凡与 **§8** 冲突之处，**以 §8 为准**。
>
> **2026-10-15 更新**：`/dfs-exec` 已把 §8.5 施行顺序的 ①②③ 全部落地（**§10 实施回写**；PR #136）。⚠️ **但按 §4.3 的自设门槛，本决策此刻仍 MUST NOT 宣称「已实现」** —— 裁判集（第 ④ 步）一行未扩，首个落点因此只在 **A1 书信体**上产生真实迭代价值（见 §10.3 的适用性闸门）。
>
> **2026-10-15 二次更新（第 ④ 步部分完成，见 §11）**：裁判集已扩到 A1 语法层，**门槛部分抬升**。用户签批的**宣称口径 = 限定表述**：「裁判已扩到 A1 语法维度：动词位置 + 格的使用三规则 error 级、时态一致性 advisory；语序经实测评审判定不做」。⚠️ **无条件「已实现验证驱动 agent 循环」继续禁用** —— 判据表 8 条中第 8 条（"浅裁判是否真被模型针对"的对照实验）因缺 `DEEPSEEK_API_KEY` 未做，故门槛**未完全解除**。

---

## 1. 背景与问题 (Context)

用户提问：*「不换主体语言，能不能加入 agent 元素？」*

### 1.1 与上游 ADR 的自洽前提（本篇必须遵守，不得越过）

| 上游 | 约束 | 对本篇的含义 |
| --- | --- | --- |
| **ADR-0021**（Accepted） | 继续 Python 主体；**语言选择以「运行时/交付」为判据**，「编辑期少犯错」用工具纪律解决 | 本篇**不动主体语言**，故不触碰该判据 —— 天然合规 |
| **ADR-0010 §5**（Accepted） | 红线：**交互请求不加 Go 代理跳**；已知词判定不离开本机 DB；Go 只管批处理内容生产 | agent 元素若落在**交互层**，必须留在 Python |
| **ADR-0001 §1**（Accepted，native-agent） | 明确抛弃 LangGraph / CrewAI / AutoGen 等重型框架 | 循环须自研，零新框架依赖 |
| **ADR-0001 §2.1**（Accepted） | 「**确定性反馈**：任务完成依据客观环境 Diff/状态码判断，拒绝大模型自我安慰式回复」 | 这是本篇的地基原则 |

> ⚠️ ADR-0021 §5 的**判据边界**明确写了「若将来…仍可另开 ADR 评估」。本篇不触及运行时性能判据，故**不构成**对该边界的挑战。

### 1.2 「agent 元素」的可证伪定义（本篇的前提）

本篇拒绝把「给 LLM 套一个 `for` 循环」称为 agent。**三条必要条件，缺一即不成立**：

1. **有界循环** —— 多轮推进，且有明确终止条件与轮次上界；
2. **工具调用** —— 模型输出驱动**真实副作用或真实数据获取**，而非纯文本生成；
3. **验证驱动迭代** —— 每轮结果被**独立于生成方的判据**裁决，不达标则带证据回炉。

### 1.3 实测基线（2026-10-14 物理核实，非引述文档）

| 探针 | 实测结果 | 结论 |
| --- | --- | --- |
| 全仓 grep `tool_calls` / `function_call` | **零命中** | 无工具调用 |
| `_ai_polish_call`（`delector/routes/main.py:2363-2411`） | 严格 **one-shot**：调一次 → `json.loads` → 返回；无校验、无重试、无迭代 | 无循环、无验证 |
| `error_count` 取值（同上） | `parsed.get("error_count", len(notes_zh))` —— **直接采信模型自报字段** | 模型自我安慰 |
| LLM 调用点 | **5 处裸 HTTP**：`main.py:415 / 518 / 1451 / 1546 / 2376`，每处各自重复 `httpx.AsyncClient` + `chat/completions` + `Authorization: Bearer` + 手工 `json.loads` | 无 client 抽象、无预算护栏 |
| `analyze_a1_email`（`delector/services/writing.py:607`） | **纯规则**判定（称呼 / 逗号后小写 / 结束语 / 结束语后禁逗号 / 字数 25–35 / Leitpunkte），**零 LLM**，已被测试覆盖 | ✅ **确定性裁判现成存在** |
| 其它确定性算力 | `services/syntax_score.py`（7 维难度）、`tools/vocab_stats`（覆盖率）、`nlp_engine/`（spaCy 形态学/句法树） | ✅ 可作裁判或工具 |
| 工具分发骨架 | `delector/routes/tools.py` `POST /api/tools/{tool_name}` 按 `TOOL_REGISTRY`（6 工具）分发，含 `_require_localhost` 闸 | ✅ 工具调用面已存在 |

**准确定性结论**：DeLector 交互层当前不是 agent，而是**五次无状态的「LLM 取神谕」**。

### 1.4 为什么「验证驱动」在 DeLector 才谈得上（本 ADR 的核心洞察）

绝大多数对话式 agent **没有裁判**，只能让模型自评 —— 不可证伪，因此「验证驱动」在那些场景里只是话术。

DeLector 的反常之处：它手里有**确定性验证器**（§1.3 末三行）。这意味着「生成 → 裁决 → 带证据回炉」这条闭环在**机械上可断言、可测试、可复现**。这既是本 ADR 成立的前提，也是它与「加个 LLM 循环」的根本区别。

---

## 2. 决策驱动 (Decision Drivers)

- **用户可见诉求（2026-10-14 审讯后上移至首位）**：润色结果**正确**且**等待可接受** —— 用户点一次「AI 润色」就得到更好的德语信，而不是等一个会自我迭代的黑盒。
- **开发者诉求（非终端用户诉求，审讯修正）**：要真实的 agent 工程经验，但**不得违背 ADR-0021**（不换主体语言）。原提案把它列为"用户诉求"占用了用户席位，实际收益方是作者/作品（§5 自认目标是"工程叙事"）；**开发者即用户**本可构成完整理由，但 MUST 明示其性质并排在用户可见指标之后。
- **可证伪性**：agent 必须有可断言的定义（§1.2），拒绝自我命名的「agent」。
- **确定性优先**：判据必须独立于生成方（ADR-0001 §2.1）——否则是奖励黑客。
- **零新依赖 / 零新框架**：沿用标准库 + 现有 `httpx`（ADR-0001 §1）。
- **可测性**：**不依赖真实 LLM Key 也能测**（stub 注入），否则门禁永远 skip。
- **边界不动**：交互层留 Python；Go 批处理侧边界与功能不变（ADR-0010）。

---

## 3. 考虑过的选项 (Considered Options)

| 选项 | 内容 | 取舍 |
| --- | --- | --- |
| **A** | **不加**任何交互层 agent 元素；agent 语义只由 Go 批处理侧承载 | 👍 零新复杂度、零 token 成本、不碰交互路径。<br>👎 交互侧永远停在「取神谕」；且 Go 侧**尚未闭环**（§4.4 红灯）⇒ 等于两边都没有 agent 语义。 |
| **B** ✅ | **交互层引入有界验证驱动循环**（首个落点：`ai-polish` 用 `analyze_a1_email` 作裁判） | 👍 判据现成、零新依赖、可 stub 测试、结构性消除「越改越错」。<br>👎 引入轮次成本与延迟；**裁判集是真实工作量**（见 §4.3）。 |
| **C** | 引入通用 agent 框架（LangGraph / CrewAI 等） | 👍 开箱即用的编排与工具协议。<br>👎 **ADR-0001 §1 已逐字否决**（过度抽象、黑盒流式、难做确定性验证）；且与「零框架」定位冲突。 |
| **D** | 用 Go 重写交互层 agent runtime | 👍 单一静态二进制、原生并发。<br>👎 **ADR-0021 §4.1 已否决**（spaCy 无等价物、Android 无落地路径、削减交付物自省）；且违反 ADR-0010 §5 红线。 |
| **E**（审讯新增） | 单次生成 + **终局验证守卫**（verify-on-stop），不做循环 | 👍 token 成本最低、延迟最可预测；行业证据：`06-Sources/Papers/HARNESS-ENGINEERING-ELEVEN-SYSTEMS.md:74` 记录 Hermes 用退出守卫"以极低 token 代价达成同等效果"。<br>👎 放弃"模型驱动探索"（Q1-B 的目标）⇒ 不满足 §1.2 条件 2。**部分吸收**：其守卫形态并入 Q3-A 的「收尾终审」；独立的 E（完全不做循环）被否。 |

> **2026-10-14 审讯补充**：表内 **B** 被采纳，但其**实现形态**经审讯修正（流转改由模型驱动、工具面收窄为任务级白名单、收尾必须过裁判终审）—— 见 §4.2 与 §8。原提案的 B 形态（**代码驱动**的回炉重试）按库内 `01-Rules/AGENT-SDK-PATTERNS` 模式 1 的分类属于 **Workflow**，流转由代码预定义 ⇒ **不满足 §1.2 条件 2**，因此不足以兑现"agent 语义"这一立论。

---

## 4. 决策 (Decision Outcome)

### 4.1 结论：**能加，且不需要换主体语言**

- **可以** —— agent 是**架构形态**属性，不是语言属性。ADR-0021 管的是「主体语言」，不管「是否引入自主循环」。
- **落在哪** —— **Python 交互层**。Go 侧仍专司批处理内容生产（ADR-0010 §5 红线不变）。
- **形态** —— 采纳 **Option B**：有界、带确定性裁判的验证驱动循环。

### 4.2 首个落点：`ai-polish` 验证驱动循环

现状（`main.py:2363` `_ai_polish_call`）：one-shot 润色，改错了无从知晓。

目标形态（**2026-10-14 审讯后定稿**；与原提案的逐条差别见 §8）：

```
        ┌─ 模型决定探索：要不要调工具、调哪个（工具面 = 任务级白名单）
        │
LLM 生成 ──┤  无工具调用 ⇒ 收尾请求
        │                 ↓
        │            【收尾终审】无裁判裁决 ⇒ 驳回，强制补一次裁判
        └─ 有工具调用 ⇒ 执行（同进程直调）⇒ 结果作为消息回给模型 ⇒ 下一轮
                          ↓
                    裁判裁决：违规 ⇒ 带【具体违反的规则 + 证据】回炉
                              合规 ⇒ 收敛返回
                        达轮次上界 / 违规数不降 ⇒ 返回最优候选（argmin）+ 显式原因码
```

- **裁判**：`analyze_a1_email`（`services/writing.py:607`），已存在、已测试、零 LLM。**收尾必须过它**（verify-on-stop 守卫）—— 模型无权在无裁决的情况下终止（依据：`01-Rules/AGENT-SDK-PATTERNS.md:47` 的"需外部裁判的任务 ⇒ 必须由人类定义的安全阀兜底"）。
- **有界**：轮次上界默认 3；**并加循环级 `{max_tokens_total, deadline_s}`**，每轮前置检查，任一超支即 `break` —— 轮次 ≠ token/时间上界，且 `deadline_s` MUST 严格小于外层请求超时（到点次序）。
- **工具面（任务级最小权限，MUST）**：本任务只暴露**只读且相关**的工具（`writing_check` + 形态/词形类）；`ingest`（拉外网）/ `export`（读库）/ `tts` **一律不暴露** —— 润色输入是用户粘贴的文本，可能夹带注入指令（防上下文投毒）。工具面作为**循环参数**注入，不是全局 `TOOL_REGISTRY`。`_require_localhost` 管"谁来调"、管不了"模型能调什么"，两者 MUST 分开对待。
- **工具调用落点**：**同进程直接调用**工具函数（HTTP 自环 = 额外故障面 + 序列化开销 + 闸语义错位）；权限 / 审计闸重定位为**工具调用前置钩子**（`01-Rules/AGENT-SDK-PATTERNS.md:90` 模式 2 要点 5）。

### 4.3 ⚠️ 关键保留：工程量在「扩裁判集」，不在「写循环」

实测 `analyze_a1_email` 目前**只查 5~6 类浅规则**（称呼、逗号后小写、结束语、结束语后禁逗号、字数 25–35、Leitpunkte 覆盖）。

**浅裁判 + 循环 = 奖励黑客**：模型会学会「通过检查」而非「写得更好」，此时循环产出的是**演示，不是 agent**。

⇒ 本 ADR 的**主要工作量**是**扩充裁判集**至 A1 真实评分维度（**动词位置、时态一致性、语序（主谓宾/情态动词框架）、格的使用**），循环只是它的执行器。**裁判集未扩到位之前，本决策不得宣称已实现。**

### 4.4 实施前置（本 ADR 的硬性门槛，缺一不得开工）

实测发现 Go 侧存在两个未闭合红灯，它们不是本 ADR 的内容，但**先于本 ADR 的实施**：

| 红灯 | 证据 | 性质 |
| --- | --- | --- |
| **① 真链路门禁是真红** | `TestEncounterRealChain` 真跑 **FAIL**（`integration_encounter_test.go:107`：import-pack 后断言 2 行，实得 **9** —— 未扣除 `create_app()` 启动时注入的 7 篇预置短文） | 断言假设空库；且该门禁**从未进 CI**（全 workflow 零处 `-tags integration`）⇒ 「绿在省略里」 |
| **② 本机该门禁恒 skip** | `integration_test.go:57` 用 `exec.LookPath("python")`，本机 `python`=3.14（无依赖）而 `python3`=3.11（依赖俱全） | 开发机上永远拿不到真实信号 |

⇒ **实施顺序（B → C → A）**：① 修 Go 门禁两红灯并接入 CI（还欠账，低风险）→ ② LLM client 收口（5 处重复收敛 + 超时/重试/**token 预算**，循环的前提护栏）→ ③ 扩裁判集 + 落验证循环。

### 4.5 明确不做

- ~~不引入 function calling / 可选工具披露 —— 当前工具链固定，JSON 契约已足够（YAGNI）。~~ **2026-10-14 审讯推翻**：该条 YAGNI 只在"流转由代码定义"时成立；一旦采纳 Q1-B（流转由模型驱动），**模型必须能选择工具**，故选工具能力由"可选"变为**必需**。取代它的约束是"工具面按任务最小化"（§4.2），**不是**"不让模型选工具"。
- 不改 Go 侧边界与功能（ADR-0010 红线）。
- 不引入任何 agent 框架（ADR-0001 §1）。
- 不把本轮扩成「通用对话 agent」。

---

## 5. 后果与代价 (Consequences)

- 🟢 **正面**：交互侧首次获得可证伪的 agent 语义（循环 + 工具 + 确定性验证）；结构性消除「AI 越改越错」；产出真实 Go/Python 双向工程叙事；零新依赖。
- 🔴 **负面**：① 循环带来**成倍 token 成本与延迟**（需 §4.4 ② 的预算护栏兜底）；② **裁判集扩充是真实工作量**，且是成败所在；③ 浅裁判场景下可能退化为奖励黑客（§4.3 已列为阻断条件）。
- 🛡️ **合规护栏（MUST）**：
  - 断言「**第 2 轮违规数严格少于第 1 轮**」，否则判失败 —— 这是真门禁，非假绿；
  - 轮次**必须有上界**，超界必须**显式声明未收敛**（零静默失败）；
  - 测试**一律 stub**，不得依赖真实 `DEEPSEEK_API_KEY`（否则门禁恒 skip，复现红灯 ②）。

---

## 6. 迷雾区 (Fog of War)

> **2026-10-15 状态回写**（实施后逐条收窄；原始表述保留在括号内以免漂移）。**详细证据见 §10。**

| # | 原表述 | 现状（2026-10-15） | 依据 |
| --- | --- | --- | --- |
| **Unknown 1** | 裁判集能扩到多深：A1 真实评分维度中，哪些可纯规则化、哪些必须 LLM 辅助？（未测） | 🟡 **部分收敛：四项点名维度已实测出可判定性谱**（详见 §11）。**动词位置** ✅（主句 V2 + 8 豁免，error 级）· **格的使用** ✅（冠词-名词一致 / 介词支配格 / 动词支配格三规则，error 级）· **时态一致性** 🟡（advisory，样本 7 错 + 6 对照）· **语序（主谓宾/情态框架）** ❌ **测后判定不做**（负样本 6/7 + 样本外正确句 3/3 误报 ⇒ **FP 与 FN 同源**）。⚠️ 仍在的门槛：**"浅裁判是否真被模型针对"的对照实验未做**（需真 Key）⇒ 宣称只能**限定**（见状态行）。 | §11 |
| **Unknown 2** | 循环的 token 成本上界与收敛率：单篇润色的实际轮次分布未测（需先有真 Key 或 stub 基线）。 | 🟡 **上界已定案，收敛率仍未测**。上界（stub 基线实测）：最坏输入 2000 字符跑满 3 轮 ⇒ 单轮最坏 **691 token**、3 轮合计 785、保守口径 3×691=2073 ⇒ `DEFAULT_MAX_TOKENS` 保留 **4096**（2.97× 余量）、循环级 `max_tokens_total=4096`（**刻意 < 4096×3**，使循环级预算真会咬合而非真空闸）、`deadline_s=18.0`（严格小于前端 `DEFAULT_TIMEOUT_MS=25000`，内层先到点）。⚠️ **折算系数 3.0 是 UNVERIFIED 假设**（本机 `tiktoken`/`transformers` 实测均 `ModuleNotFoundError`，拿不到真 BPE 计数）；**真实轮次分布**须有 Key 后回测。 | §10.2 |
| **Unknown 3** | 是否需要 function calling：当前固定工具链用 JSON 契约足够，但若扩到多工具编排需重估。 | 🟢 **已定案 = JSON 契约字段**（回复里的 `tool_call: {name, payload}`），**不用**原生 `tool_calls`。三条理由（可 stub / 与 `llm_client.chat` 的 dict 返回同形且不动刚收口的 client / 零新依赖）。**重估触发条件保留**：若将来扩到多工具编排再议（§8.3 的"暴露全部 6 工具"仍被否）。 | §10.4 |
| **Unknown 4** | → 见 §4.4：Go 侧两个红灯未修完前，实施顺序 ③ 不启动。 | 🟢 **已闭合**。① 断言被预置短文污染 ⇒ 改为**前后快照相对断言**（净增恰好 2 行）；② 本机恒 skip ⇒ 解释器探测改**候选链**（`$DELECTOR_PYTHON`→`python3`→`python`，逐个实测 `import uvicorn, fastapi`）；更关键的是**执行期发现的第三个红灯**：门禁把 `baseURL` 硬编码 8001 且**不校验服务身份** ⇒ 起服 bind 失败后仍向该端口发业务请求（实测打到 3 小时前的孤儿 uvicorn，**真实风险不是假红而是假绿**——替别人的服务背书）⇒ 补身份探针 + fail-fast + 动态端口。门禁已**接入 CI**（零 SKIP 判据 + `-count=1` 防 Go 缓存复用）。 | §10.1 |
| **Unknown 5**（新，§8.4 遗留） | `lookup_core_vocab`（`writing.py:680`）的异常路径是否抛 **UNVERIFIED** | 🟡 **已探但未穷尽**：`analyze_a1_email` 10 组边界输入（空串/纯空白/5000 字符/emoji/300 个变音字母/缺结语…）全通过，`lookup_core_vocab` 10 组边界词 0 失败 ⇒ **未见抛出**。`judge_error` 单轮降级保留为**防御性守卫**（成本极低），不再作为"待收窄的假说"。 | §10.5 |

---

## 7. 关联 (References)

- **ADR-0021**（stay-on-python 判据 · §5 判据边界「日后可另开 ADR 评估」）· **ADR-0010**（§5 交互层留 Python 红线 · Go 只管批处理）· **ADR-0001**（§1 零框架 · §2.1 确定性反馈）· **ADR-0018**（§4 D5 Python 不可移除）
- 代码锚点：`delector/routes/main.py:2363`（`_ai_polish_call`）· `delector/services/writing.py:607`（`analyze_a1_email`）· `delector/routes/tools.py`（工具分发）· `agent/integration_encounter_test.go:107`（红灯 ①）· `agent/integration_test.go:57`（红灯 ②）
- `08-Projects/DeLector/GO-PYTHON-HYBRID-ARCHITECTURE.md`（Go/Python 边界与进程坑）
- `08-Projects/native-agent/01-ADR/0001-native-go-workspace-agent-architecture.md`（Go 侧零框架 harness，**0 行代码**，本 ADR 判定其暂不启动）

---

## 8. 本次审讯的修正与定稿（2026-10-14 · `/dfs-grill` Track 2）

> 审讯方式：双镜并行席位（**product-ux** 用户价值层 + **sre-resilience** 韧性层）+ 逐条对表库内 `01-Rules/AGENT-SDK-PATTERNS`（Pi 六模式）与 `06-Sources/Papers/HARNESS-ENGINEERING-ELEVEN-SYSTEMS`。**本节与正文冲突之处，以本节为准。**

### 8.1 拍板记录（用户四问）

| 问 | 决策 | 落点 |
| --- | --- | --- |
| Q1「agent 语义」靠什么兑现 | **B：流转改由模型驱动**（模型自选工具；代码只做二值判断——有工具调用则继续、无则请求收尾）。依据 `AGENT-SDK-PATTERNS` 模式 1 要点 7 | 使 §1.2 条件 2 成立；§4.5 原"不做 function calling"被推翻 |
| Q2 循环成本与出口 | **A：保留上界 3 + 三件 MUST**（循环级 `{max_tokens_total, deadline_s}` 前置检查 / UI 逐轮进度 + 取消 / `converged` + 原因码进返回契约且前端 MUST toast） | §4.2、§5 |
| Q3 谁决定"可以收尾了" | **A：模型先行、裁判终审**（无裁判裁决 ⇒ 驳回，强制补一次裁判） | §4.2「收尾终审」；与 Hermes verify-on-stop 同一条线 |
| Q4 模型可调工具面 | **A：任务级最小白名单**（只读且相关；`ingest` / `export` / `tts` 不暴露；工具面为**循环参数**） | §4.2「工具面」 |

### 8.2 随拍板一并定稿的七条

1. **运行时停止策略**：`v_n ≥ v_{n-1} ⇒ break`，回退 `argmin(v)` 候选，置 `converged=false` + 原因码 `no_improvement`。§5 那句"断言第 2 轮违规数严格少于第 1 轮"是**测试断言口吻**，MUST 同时存在等价的**运行时策略**，否则默认行为是"用更多 token 换等价或更差结果"。
2. **裁判可信性哨兵**：`v_n == v_{n-1} and n≥2 ⇒ judge_unreliable` 提前停；**裁判异常**按 errors-as-messages 单轮降级（异常作为消息回给模型，**不得 500**）。
3. **人类裁决环 MUST**：输出必须走既有逐 hunk「采纳润色 / 保留原句」UI（`static/js/writer.js:1170-1174`）；用户"保留原句"的 hunk 即**裁判集不足的回归信号**（§4.3 的工程质量由此接上外部反馈）。
4. **决策驱动改词**：开发者诉求从"用户诉求"下移并明示其性质；首位换成用户可见指标（见 §2）。
5. **工具调用落点**：同进程直调 + 权限闸作前置钩子（见 §4.2）。
6. **证据注入预算**：违规证据逐轮注入前 MUST 按"行数 + 字节"双限截断（模式 4 层 1），否则循环级 `max_tokens_total` 会被自己的证据撑爆。
7. **归档形式**：修订本篇（`proposed → accepted`）而不另开 ADR-0024 —— 本篇从未被接受，无需保存历史。

### 8.3 被否决的形态与理由（防将来重走）

- **原 B 形态（代码驱动的回炉重试）**：按模式 1 分类属 **Workflow**（流转由代码预定义），**不满足 §1.2 条件 2** ⇒ 拿不到它宣称的 agent 语义（诚实改名"验证驱动自反思重试"才行）。
- **纯 verify-on-stop（选项 E）**：成本最低且有行业背书，但主动放弃"模型驱动的探索"；仅吸收其守卫形态作**收尾终审**。
- **暴露全部 6 工具 + 只靠 `_require_localhost` 闸**：把"谁来调"当成"能调什么"；在润色输入可被注入的语境下，等于把 `ingest`（外网）与 `export`（读库）交给模型（库内 `02-Distilled/AGENT-GOVERNANCE-SECURITY.md` 的"任务级最小权限 / 防上下文投毒"在单机单进程下的等价物）。

### 8.4 两席发现的原文级证据（保留以备复核）

- **product-ux（P0）**：循环成本落在唯一交互点，而 UI 只有置灰按钮（`static/js/writer.js:1229-1231`，无进度、无取消）；单轮 `timeout=30`（`main.py:2374`）× 上界 3 ⇒ 最坏 ≈90s。
- **product-ux（P1）**：§2 的"用户诉求"实为作者诉求；现有**人类裁决环**未被 ADR 引用。
- **sre-resilience（P0）**：循环只有轮次上界，token/时间上界**不可计算**（生成 payload 无 `max_tokens`，`main.py:2378-2385`；DeepSeek 默认输出上限 **UNVERIFIED**）。
- **sre-resilience（P1）**：`converged` 不在真实返回契约里（`main.py:2420-2427`）⇒"零静默失败"无处落地；裁判依赖 `lookup_core_vocab`（`writing.py:680`）的异常路径未定义（是否抛 **UNVERIFIED**）。

### 8.5 施行顺序（不变：§4.4 两红灯仍先于本 ADR）

① 修 Go 门禁两红灯并接入 CI → ② LLM client 收口（5 处重复 HTTP 收敛 + 超时/重试 + **token 预算** + `max_tokens`）→ ③ 本 ADR 的循环 + 工具白名单 + UI 进度/取消 → ④ 扩裁判集（§4.3，成败所在）。

---

## 9. 语言边界的再确认（2026-10-14，防重复争论）

> 触发：用户问「我们 agent 开发也是在 Python 基础上吗？Go 能使用吗？」—— 本节把结论固化，避免同一问题被反复撬动。

### 9.1 事实：本项目的 agent 已经是**双语言**，不是"Python 基础"

| 落点 | 语言 | 职责 | 证据 |
| --- | --- | --- | --- |
| **交互层 agent 循环**（本篇） | **Python** | `ai-polish` 的验证驱动循环 | §4.2；裁判 `analyze_a1_email` 在 `delector/services/writing.py:607`（Python） |
| **批处理层 agent** | **Go（已在跑）** | encounter zone 内容生产 | `agent/go.mod`：`go 1.26` + `github.com/sashabaranov/go-openai` + `spf13/cobra`，含 `cmd/` `internal/` 与 integration 测试 |
| **Go 原生 agent harness** | Go（**0 行代码**） | 独立工作台 agent（零框架 + 原生并发） | vault `08-Projects/native-agent/01-ADR/0001-native-go-workspace-agent-architecture.md` |

⇒ 「Go 能不能用」的答案是：**已经在用，且用的正是它最适合的那一层**（边界由 ADR-0010 §5 红线划定：交互请求不加 Go 代理跳）。

### 9.2 判据（沿用 ADR-0021，不新造）

- **语言选择以「运行时 / 交付」为判据**，「编辑期少犯错」用工具纪律解决（ADR-0021 标题即此）。
- 实测（以本仓 14 条真实缺陷做可证伪分类）：**换 Go/Rust 至多在编译期消掉 ≈21%（3/14），其余 ≈79% 原样保留**。
- 换主体语言的代价：**两套 runtime + IPC**、**产物自省被削弱**（静态二进制是 blob，只能 `strings`/`nm`，而本仓多数事故靠读产物发现）、**原生段崩溃不可 recover**（`try/except → launch.log + 弹窗` 这层"绝不静默失败"失效）。

### 9.3 评估矩阵（本项目语境下的真实差异）

| 维度 | Python（交互层） | Go（批处理 / native-agent） | 本项目事实 |
| --- | --- | --- | --- |
| **裁判可得性** | ✅ 决定性：spaCy 形态/句法、`analyze_a1_email`、`syntax_score`、`TOOL_REGISTRY` 6 工具全在 Python | ❌ 无等价物（spaCy 不可搬） | 本篇 §1.4 的立论就是"裁判现成" |
| **交付面** | ✅ Desktop 壳（pywebview）/ Android（Chaquopy）/ 便携包在 Python 侧 | 静态二进制（自己的产物） | 交互层 agent 的收益必须出现在用户点的那一屏 |
| 并发 / 长任务 | asyncio 够用；CPU 重活得绕 GIL | ✅ 原生并发 + 单二进制 | 循环内无 CPU 热点（ADR-0018 已测解释器开销非瓶颈） |
| 编译期保障 | mypy 四档（已上） | ✅ 更强 | 但只多消 ≈21% 缺陷 |
| 产物自省（运维） | ✅ 数 DLL / `unzip -l` 读 APK / 探针 | ❌ blob（`strings`/`nm`） | 本仓多数事故靠读产物发现 |
| LLM 接入 | httpx 裸 HTTP ×5（正在收口） | ✅ `go-openai` 已在用 | 两边都有现成路径 |
| 框架依赖 | 零框架自研 | 零框架自研 | 一致 |
| **模式层损失** | — | — | **零**：`01-Rules/AGENT-SDK-PATTERNS` 明说六模式"不绑定特定 API，可应用于任何基于 LLM 的 Agent 系统"（pi 是 TS 写的，我们蒸馏的是模式不是代码） |

### 9.4 结论与可复用判据

1. **对交互层循环（本篇）**：Python 不是偏好而是必然 —— **裁判（spaCy/规则集）与交付面（Desktop/Android/便携包）都在 Python 侧**；换 Go 会让循环**失去裁判**，而裁判正是 §1.4 立论的前提。
2. **想用 Go 写 agent，已有正当落点**：批处理层（在跑）+ `native-agent`（设计已审、0 行代码）。启动后者是**产品/精力决策，不是技术阻塞**。
3. **可复用判据（今日新增，建议将来晋升 `01-Rules`）**：**先问「裁判在哪、交付物在哪」，再问「用哪种语言」** —— 这两问的答案决定语言，而不是反过来。
4. **要改这条边界**：门槛在 ADR-0021 §5 已写明 —— 三条翻盘条件（① 剔除 spaCy 与 IO 后解释器开销占 p95 >50%；② 热点下沉压不下去；③ Android 双运行时给出可接受体积与首启数据）**缺一不可，且需另开 ADR**。

---

## 10. 实施回写（2026-10-15 · `/dfs-exec` 执行 §8.5 序 ①②③）

> 计划正本：仓内 `docs/plans/2026-10-14-interactive-agent-loop.md`（含执行期发现与顺序调整）。PR **#136**（base master，HARD GATE 4：全程未直推）。7 个任务单元全部经 **maker-checker 双席位**独立评审，其中 3 个被判 REWORK 后回炉。

### 10.1 施行顺序 ①（Go 门禁欠账）—— **含执行期新增的第三个红灯**

- **红灯①** `64f7abf`：断言被 `create_app()` 注入的 7 篇预置短文污染（恒红）⇒ 改**前后快照相对断言**。
- **红灯②** `42e8420` / `f96a8d2`：本机恒 skip ⇒ 解释器探测改**候选链**并逐个实测依赖，**接入 CI**（零 SKIP 判据 + `-count=1` 防 Go 测试缓存复用旧 `ok`）。
- **红灯③（执行期新发现，`b76d45a`）**：门禁 `baseURL` **硬编码 8001 且不校验服务身份** ⇒ 起服 bind 失败后**仍向该端口发业务请求**（实测被 3 小时前的孤儿 uvicorn 应答 ⇒ 假红，但**真实风险是假绿**：外来服务答得对时门禁会替它背书）⇒ 补 `GET /api/health` 身份探针（**接受 503、只读 `app`/`version`**，对齐 Python 侧 `probe_identity`）+ fail-fast + 动态空闲端口。
- 现状：`go test -tags integration ./...` ⇒ **116 PASS / 0 FAIL / 0 SKIP**。

### 10.2 施行顺序 ②（LLM client 收口）—— 附带 Unknown 2 的上界实测

- `9e17399`：5 处裸 HTTP（`main.py:413/516/1449/1544/2374`，超时各写各的 30/15/20/10/30）⇒ 全部收敛到 `delector/services/llm_client.py`，**payload 必带 `max_tokens`**（收口前生成路径零设置 ⇒ 输出上界不可控，正是循环预算的前置欠账）；保留各处超时语义与失败文案。
- **Unknown 2 的上界定案（stub 基线实测，2026-10-15）**：最坏输入 = **2000 字符**（端点 `req.text[:2000]`）的真实 A1 电邮，录制桩跑满 3 轮 ⇒ completion 139/139/**2073** 字符 ⇒ 折算 47/47/**691** token；单轮最坏 **691**、3 轮合计 785、保守口径 3×691=2073。据此：`DEFAULT_MAX_TOKENS` **保留 4096**（2.97× 余量）、`max_tokens_total` 默认 **4096**（**刻意小于 4096×3** ⇒ 循环级预算真会先咬合，测试钉住"非真空"）、`deadline_s` 默认 **18.0**（严格小于前端 `DEFAULT_TIMEOUT_MS=25000`，该值从 `static/js/core.js` **现读**，测试现算现比）。
- ⚠️ **折算系数 `CHARS_PER_TOKEN_ESTIMATE = 3.0` 是 UNVERIFIED 假设**：本机 `tiktoken` / `transformers` 实测均 `ModuleNotFoundError`，拿不到真 BPE 计数（取 3.0 而非常见 4.0 = 偏保守 = 高估消耗 = 预算更早咬合）。**假设与实测在文档与代码注释里始终分开标注**；将来拿到真计数只需替换这一个常量，四条预算闸自动跟着变。

### 10.3 施行顺序 ③（循环 + 白名单 + UI）—— 与本文定稿形态的两处执行期偏离

- `ff7235a` 循环内核（`delector/services/polish_loop.py`）：二值流转（D1）/ **收尾终审守卫**（D3，无本轮新鲜裁决不许终止）/ `v_n ≥ v_{n-1} ⇒ break` + `argmin` 回退 / `judge_unreliable` 哨兵 / 每轮**前置** `max_tokens_total` 与 `deadline_s`（per-call timeout = `min(30, 剩余)`，内层先到点）/ 裁判异常 errors-as-messages / 证据注入**行数+字节双限**截断 / 零静默失败。
- `1cb60fc` 工具面（`polish_tools.py`）：白名单**恰好 3 项只读**（`writing_check`/`analyze`/`vocab_stats`，`MappingProxyType`，值取 `TOOL_REGISTRY` 真身，**同进程直调不经 HTTP**），`ingest`/`export`/`tts` 由**差集守卫**从 `TOOL_REGISTRY` 现读钉住；权限闸作**前置钩子**（串行 + fail-fast + 拒绝即返回）。
- `2e61c88` 契约与 UI：`converged` / `unconverged_reason` **只增不改**；SSE 逐轮进度（`round`/`max_turns`）+ 取消 + 未收敛 toast（前端文案表覆盖全部原因码，有集合相等测试）；`stream: bool = False` 默认关 ⇒ 既有 JSON 行为逐字不变。
- **偏离 1（适用性闸门，必须记住）**：现裁判对**非书信体**必然报 `a1_greeting_missing`（level=error），而那是**题材差异不是错误**。若照单全收：`v_0=1` ⇒ 润色后仍无称呼语 ⇒ `v_1 ≥ v_0` ⇒ 判 `no_improvement` 并回退 `argmin` = **原文** ⇒ 用户点了润色拿回原文，**功能报废**（既有基线 `test_ai_polish_diff_mocked` 实测就是这样红的）。故落闸门：称呼语不合法 ⇒ 该裁判对本文本**不适用** ⇒ 零违规。**语义上这等价于今日的一次性润色（首轮即接受），不等于「裁判判定无错」** —— 代码注释与测试均按此措辞，不宣称零错。**欠账**：闸门对**候选**同样单向生效（模型删掉称呼语 ⇒ 候选也判"不适用" ⇒ 零违规自动收敛），留 Unknown 1 续作收口。⇒ **这就是 §4.3 那句"裁判集未扩到位之前不得宣称已实现"落在实际行为上的样子。**
- **偏离 2（收敛归属必须在循环内）**：一度在端点层用录制包装兜底"收敛时取模型最后一轮的 `corrected_text`"，但 recorder **分不清取证轮与收尾轮** —— 模型若在取证轮夹带 `corrected_text` 而收尾轮没有（循环按协议回退原文作候选），收敛时就会返回**模型没被采用的文本**。改为循环内「`v==0` ⇒ 返回那个被判零违规的候选」，端点兜底整个删除。

### 10.4 Unknown 3 定案：**JSON 契约字段**（不用原生 `tool_calls`）

选定 `{"tool_call": {"name": ..., "payload": {...}}}`。理由三条（可证伪）：① **可 stub** —— 原生 `tool_calls` 需服务端配合 `tools=[...]` schema，而本仓测试红线是"一律 stub、严禁真 Key"，JSON 字段一个 dict 即可注入；② **与既有链路同形** —— `llm_client.chat` 返回值本就是 `json.loads(content)` 的 dict，且 `response_format=json_object` 已强制 JSON 输出 ⇒ 用原生形态要改刚收口的 client 契约；③ **零新依赖**（ADR-0001 §1）。代价是自解析，但解析面只有 `tool_call` 一个键。

### 10.5 §8.4 遗留 UNVERIFIED 的收窄

- **`lookup_core_vocab` 是否会抛**：探针实测 —— `analyze_a1_email` 10 组边界输入全通过、`lookup_core_vocab` 10 组边界词 0 失败 ⇒ **未见抛出**（未穷尽）。`judge_error` 单轮降级保留为防御性守卫。
- **DeepSeek 默认输出上限**：仍 UNVERIFIED，但**已不再是风险面** —— payload 现在必带显式 `max_tokens`。
- **`converged` 不在返回契约**：已闭合（见 10.3）。

### 10.6 两条执行期教训（可复用，建议晋升 `01-Rules`）

1. **SSE 的断连收尸必须放 `try/finally` 的同步 `cancel()`**，不能只在生成器里 `await is_disconnected()` 轮询：uvicorn 0.54 的 HTTP scope `spec_version="2.3"` ⇒ starlette `StreamingResponse.__call__` 会**同时**跑 `listen_for_disconnect`，它**抢先**取消生成器 ⇒ 轮询路径（真实周期是 `sleep(0.02)`）几乎永远输给它，在途请求继续烧配额。变体陷阱：只迭代 `resp.body_iterator` 的测试**绕开了 `__call__`**，因此测不到这个抢先 —— 取消用例必须自造 `receive`/`send` 驱动真响应对象。
2. **"只读"这类声称必须带前提**：`analyze` 被写成"模型缺失时降级、不下载"，实测 `nlp_engine/processor.py:95-114` 在桌面且模型缺失时会真跑 `spacy.cli.download`（出网 + 起 pip 子进程；Android 与打包产物不会走到）。修法是把它写成**条件式**（"本运行时模型可用"）+ 一条**非真空测试**（模型不可用时该测试红），而不是删掉声称。

### 10.7 未做（明确留白，非遗漏）

- **裁判集扩充（第 ④ 步）= Unknown 1**：下一个子计划。本 ADR 在此**明确停止**，不投机拆任务。
- **真实轮次分布 / 真 token 计数**：须有 `DEEPSEEK_API_KEY` 后回测（当前该 Key 在本机缺失）。
- **Android 真机点检**：本批动了 `static/`，且 **SSE 的 `fetch` + `ReadableStream` 在 WebView 上未验证**（跑不了会降级到一次性 JSON，但降级路径本身必须真机确认）。

---

## 11. 实施回写（2026-10-15 · §4.3 第 ④ 步「裁判集扩充」）

> 计划正本：仓内 `docs/plans/2026-10-15-a1-judge-expansion.md`（8 任务，台账 8/8）。PR **#137**（base master，HARD GATE 4：全程未直推）。门禁：全量 `pytest` **1984 passed + 2 skipped**；`ruff` / `mypy --strict delector`（67 files）/ 前端契约闸全绿；6 组变异自证。

### 11.1 开工前的双席位评审救了一次（值得晋升规则）

按 `01-Rules/LAYERED-ARCHITECTURE.md`（实证对象 = Pi-Agent 三层）+ `AGENT-SDK-PATTERNS` 评审本计划，最重要的发现是 **dead-green**：计划 7 个任务里**没有任何一个写"谁把 `nlp` 交给裁判"**，而生产路径 `_run_polish` 从不传 `judge=`、Out-of-Scope 又禁改内核 ⇒ **语法裁判在生产恒不生效，而全部任务测试仍会绿**、§4.3 判据表还能被打勾解除。⇒ 把「能力」与「接线缝」合并为**原子变更**，并新增**端点级**回归用例（变异自证：端点不传 `judge=` ⇒ 该用例红）。
**可复用规则**：**任何"新增判据/能力"的任务，MUST 在同一变更里指名"谁把它送进生产链路"，并有走完整链路的用例** —— 只测单元函数就是 dead-green 的温床。

### 11.2 本子计划最值钱的产出：三次「误报类」返工 + 硬门加宽

| # | 误报（全部实跑取证） | 谁发现的 |
| --- | --- | --- |
| ① | 严格 Acc 动词遇上**自由第三格**：`Ich öffne meinem Bruder die Tür.` / `Ich bezahle meinem Vater das Essen.` / `Ich schmecke den Wein.` | CRV |
| ② | V2 把**主语 NP 内修饰**当独立前置成分：`Meine sehr große Familie wohnt in Berlin.` | 编排者按 CRV 的 UNVERIFIED 探针实跑 |
| ③ | V2 漏豁免**焦点小词**（`Auch meine Familie…` / `Nur mein Bruder kommt…`）+ rektion 仍报自由第三格（`Ich lese meinem Bruder das Buch.`） | 编排者第二轮探针 |

**官方 10 篇范文门放过了全部三类** ⇒ 硬门从"10 篇"扩到 `COMMON_CORRECT_SENTENCES`（**实测 51 句** + 类覆盖清单 + `judge_engine=='rules+spacy'` 防降级假绿），编排者另做 **30 句常见正确德语广度扫雷 FP=0** 后才定稿。
**可复用规则**：① 正样本"够不够宽"本身是一类系统性风险 —— 硬门 MUST 附**类覆盖清单**（不是句子清单），将来加句子时逐类检查；② checker 判为 `UNVERIFIED` 的探针**不该只当参考**：本批两次额外误报类都是"把 checker 的探针真跑一遍"撞出来的。

### 11.3 §4.3 判据表（8 条）与签批结论

| 判据 | 实测 | 满足 |
| --- | --- | --- |
| 维度覆盖（ADR 点名四项） | 动词位置 ✅ / 格的使用 ✅（3 规则） / 时态 🟡 advisory / 语序 ❌ 测后判定不做 | **部分** |
| 官方 10 篇范文零误报 | `FP_TOTAL 0` | ✅ |
| 51 句硬门 + 引擎非降级 | 全绿 | ✅ |
| 编排者 30 句广度扫雷 | FP 0 | ✅ |
| 负样本召回（含变异自证） | ✅ | ✅ |
| 非书信文本可判 | 闸门按规则族分流（语法族任意文本生效） | ✅ |
| 降级可见性（不许"没检查"伪装成"检查通过"） | `judge_engine`/`judge_degraded` 忠实 + 前端非阻断提示 | ✅ |
| **"浅裁判是否真被模型针对"的对照实验** | **未做**（缺 `DEEPSEEK_API_KEY`） | ❌ |

**用户签批（2026-10-15）**：采用**限定表述**（「裁判已扩到 A1 语法维度：动词位置 + 格的使用三规则 error 级、时态一致性 advisory；语序经实测评审判定不做」）；**无条件「已实现验证驱动 agent 循环」继续禁用**（第 8 条未做之前不解禁）。

### 11.4 两项"测后不做/降级"的裁决（防后来者误读）

- **A 维（情态动词框架语序）= 不做**：负样本 6/7（「实词夹在情态动词与末位动词之间」整族不可见 = 结构性 FN）+ 样本外 3 句**正确**句（逗号并列主句）全部误报 ⇒ **FP 与 FN 同源**。标定产物留在仓内 `tools/bench_judge_fp.py` 作记录 —— **它不是在"待接线"**。
- **B 维（时态一致性）= 接线为 `level="warning"` advisory**：正样本 FP 0/35、负样本 7/7、对照 0/6（样本偏小）⇒ 先 advisory 不阻断收敛（`violations_of` 只认 `error`，Task 4 钉死），可见性靠响应体新增 `judge_advisories` + 前端非阻断提示；积累真实用法后再议升 error。

### 11.5 随判据表登记的已知边界（未收口，防漂移）

① **书信缺称呼语** ⇒ 判据 `greeting.valid` 归 prose ⇒ 格式族（含 `a1_greeting_missing`）**永远不被计数**（继承自旧闸门）；② 候选侧 kind 逐候选翻转（旧欠账）；③ **非书信文本模型修不动 ⇒ `no_improvement` ⇒ 回退原文**（用户签批保持；有断言 + 三处 docstring + 前端人话原因码）；④ advisory 在 argmin 回退路径下可能与出口文本不对应（不进任何计数）；⑤ warning 级条目按族分居 `violations`（格式族）/ `advisories`（语法族），取全集需并集两键。

### 11.6 未做（明确留白）

- **第 8 条对照实验**（浅裁判 vs 真变好）——需真 Key。
- **真实轮次分布与真 token 计数回测**（与 §6 Unknown 2 同一笔账；折算系数 3.0 仍是 UNVERIFIED 假设）。
- **Android 真机点检**（含新 API 在 WebView 的 `fetch`/`ReadableStream` 表现）。
- **Pi 式分层重构**（用户 2026-10-15 拍板暂缓，登记在仓内 `docs/agents/architecture.md`）。
