# -*- coding: utf-8 -*-
"""验证驱动 agent 循环的内核（Task 4 · ADR-0023 §4.2 / §8.2）。

形态（D1）：**流转由模型驱动**，代码只做**二值判断**——模型回复里

- 有 `{"tool_call": {"name": ..., "payload": {...}}}` ⇒ 执行工具、把结果作为证据追加、继续下一轮；
- 没有 ⇒ 视为**收尾候选**，交给确定性裁判终审（D3）。

## Unknown C 的选定结果（本次定案，待编排者回写 ADR §6）

**选定：JSON 契约字段**（回复里的 `tool_call` 键），**不用** OpenAI 原生 `tool_calls`。
理由（每一条都可证伪）：

1. **可 stub**：原生 `tool_calls` 需要服务端配合 `tools=[...]` 的 schema，而本仓测试红线是
   「一律 stub、严禁真 Key」—— JSON 字段只要一个 dict 就能注入，桩成本几乎为零；
2. **与既有链路同形**：`llm_client.chat` 的返回值本就是 `json.loads(content)` 的 dict，
   且 `response_format=json_object` 已强制 JSON 输出 ⇒ 用原生形态要改 client 契约，
   JSON 字段不用动 client（Task 3 刚收口，不再开刀）；
3. **零新依赖**（ADR-0001 §1 红线）：不依赖任何 agent 框架。
   代价是自己解析，但解析面只有 `tool_call` 一个键，明确小于引入 schema 体系的面。

## 预算实测（2026-10-14 实测，非引述）

- **tokenizer 探测**：本机 `import tiktoken` 与 `import transformers` **均为
  ModuleNotFoundError** ⇒ **没有真 tokenizer**。故 token 数一律走 `estimate_tokens()`
  的**字符折算**，折算系数 `CHARS_PER_TOKEN_ESTIMATE` 登记为 **UNVERIFIED 假设**
  （可证伪：将来拿到真计数，只替换这一个常量，测试仍然成立）。
- **最坏输入**：2000 字符（`delector/routes/main.py:2383` 的 `req.text[:2000]`，端点真实
  输入上限）的真实德语 A1 电子邮件。
- **录制桩跑满 3 轮**：不出网，记录每次 `(messages, max_tokens, timeout)`，实测每轮
  prompt / completion 的字符数与字节数；原始数字由
  `tests/test_ai_polish_loop.py::measure_worst_case_three_turns()` **现算现比**。
- **实测原始数字（2026-10-14）**：prompt 2373 / 2439 / 2505 字符（2687 / 2761 / 2835 字节），
  completion 139 / 139 / 2073 字符（139 / 139 / 2119 字节）⇒ 折算 47 / 47 / 691 token；
  单轮最坏 **691**，3 轮合计 **785**（保守口径 3×691 = 2073）。
- **轮次分布（stub 基线）**：收敛于第 1 轮 = 首轮直接收尾且 `v_1 == 0 < v_0`；第 2 轮 = 首轮
  取证、次轮收尾且 `v_2 == 0 < v_1`；第 3 轮 = 前两轮取证、末轮收尾且 `v_3 == 0 < v_2`。
  任一处「不再下降」即停在 `no_improvement` / `judge_unreliable`。
  注意这是**桩场景**的分布（取几次证由模型自己定），不等于真实分布 —— Unknown B 的
  「真实轮次分布」仍有待有 Key 后回测，本模块只保证**上界**成立。
- **定案**：`DEFAULT_MAX_TOKENS`（per-call）**保留 4096**（实测单轮最坏需求 ×2 仍余量充足）；
  `DEFAULT_MAX_TOKENS_TOTAL = 4096`（= 一次满额 per-call 的量，语义好讲：
  「整个循环最多烧掉一次满额回复的量」；它严格小于
  `DEFAULT_MAX_TOKENS * MAX_TURNS_DEFAULT = 12288` ⇒ **循环级预算会先于**
  「每轮上限 × 轮数」咬合，不是真空闸）；`DEFAULT_DEADLINE_S = 18.0`（严格小于
  `static/js/core.js` 的 `DEFAULT_TIMEOUT_MS / 1000 = 25.0`，留 7s 给端点回程与 toast
  ⇒ **内层先到点**，前端拿到的是人话原因码而不是 abort）。

## 计量口径

`max_tokens` 只约束 **completion**，故循环预算 `max_tokens_total` 也**只累计 completion**
—— 两者同单位，循环级预算才有可对照的意义（否则「总量 < 每轮上限 × 轮数」这条闸无从谈起）。
优先取 `chat` 返回 dict 里的 `usage.completion_tokens`（真链路形态）；**当前**
`llm_client.chat` 只回 `json.loads(content)`，不带信封里的 `usage` ⇒ 真链路今天走
`estimate_tokens()` 估算路径；等 client 把 `usage` 合并进返回值，同一行代码自动切到精确计量。

## 不变量（由 `tests/test_ai_polish_loop.py` 钉住）

- `converged=True ⇒ reason == "ok"`；未收敛 MUST 带原因码（零静默失败）；
- 收尾候选 MUST 有**本轮新鲜裁判裁决**（D3），否则驳回并强制补跑一次裁判；
- 每轮开始**之前**先查 `max_tokens_total` 与 `deadline_s`，超支即带原因码退出；
- **每次 `dispatch` 都受超时约束**（Task 8 接缝①）：`min(DEFAULT_PER_CALL_TIMEOUT_S, 剩余 deadline)`，
  剩余 deadline 在调用前**重算**；`asyncio.TimeoutError` ⇒ errors-as-messages（喂回模型），
  **不炸循环、不冒泡** —— 收口仍由轮首的预算前置检查给原因码；
- **同步裁判 MUST 移出事件循环**（Task 8 接缝②）：经 `asyncio.to_thread` 跑
  ⇒ 长裁判不阻塞同进程其它路由，且 `task.cancel()` 掐得断在途裁判
  （线程本身掐不断，但循环不再等待它）；注入 async 裁判时直接 `await`
  （否则 `to_thread` 会把 coroutine 对象当返回值 ⇒ 静默假收敛）。

## 刻意不做

- **不碰** `delector/routes/main.py` / `static/js/*`（Task 6 的活）；
- `chat` 抛异常（`llm_client.LLMError`）**原样冒泡**：原因码集合里没有「上游失败」这一项，
  编一个原因码就是替上游撒谎；端点侧已有 502 映射，交给它；
- `on_progress` 回调抛异常同样**原样冒泡**（UI 回调不该被静默吞掉）。
"""

import asyncio
import inspect
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping

from delector.core.database import get_effective_api_model
from delector.services import llm_client
from delector.services.writing import analyze_a1_email

# ── 轮次与预算常量 ────────────────────────────────────────────────────────────
MAX_TURNS_DEFAULT = 3

# token 折算系数（**UNVERIFIED 假设**）：本机无 tiktoken / transformers（实测
# ModuleNotFoundError），拿不到真 BPE 计数，故按"N 个字符 ≈ 1 个 token"折算。
# 取 3.0 而不是常见的 4.0：德语变音字母（ä/ö/ü/ß）在 UTF-8 里是双字节，主流 BPE
# 常把它拆成多个 token ⇒ 折算**偏保守**（高估消耗 ⇒ 预算更早咬合 ⇒ 安全方向错）。
# 可证伪：将来拿到真 tokenizer，只改这一个常量，`estimate_tokens()` 与预算实测一起跟着变。
CHARS_PER_TOKEN_ESTIMATE = 3.0

# per-call 上限沿用 `llm_client.DEFAULT_MAX_TOKENS`（4096，Task 3 的占位值）：
# 实测单轮最坏需求约 700~740 token（见 `tests/test_ai_polish_loop.py`），
# 2× 余量 = ~1480 ⇒ 4096 余量充足，**保留不改**。
#
# 循环级总量 = 一次满额 per-call 的量：
#   DEFAULT_MAX_TOKENS_TOTAL (4096) < DEFAULT_MAX_TOKENS (4096) × MAX_TURNS_DEFAULT (3)
# ⇒ 证明它会在「第 1~2 轮跑飞」时咬合，而不是永不触发的真空闸。
DEFAULT_MAX_TOKENS_TOTAL = 4096

# 墙钟 deadline：MUST 严格小于外层请求超时（到点次序：内层先到点才能留下人话错误）。
# 外层 = `static/js/core.js` 的 DEFAULT_TIMEOUT_MS = 25000ms = 25.0s（测试从该文件现读，
# 不抄常量）；25.0 − 7.0 = 18.0，7s 留给端点回程 + 前端 toast 渲染。
DEFAULT_DEADLINE_S = 18.0

# 单次 chat 的默认超时：`delector/routes/main.py:2363` 的 ai-polish 现值 30.0s（语义不变）。
# 实际取值 = min(它, 剩余 deadline) —— 剩余 ≤0 时循环直接带 `deadline` 原因码退出。
DEFAULT_PER_CALL_TIMEOUT_S = 30.0

# ── 证据注入双限（**两个限都要真起作用**，各有对应用例） ──────────────────────
EVIDENCE_MAX_LINES = 40
EVIDENCE_MAX_BYTES = 4000

# ── 原因码 ────────────────────────────────────────────────────────────────────
REASON_OK = "ok"
REASON_NO_IMPROVEMENT = "no_improvement"
REASON_TURN_LIMIT = "turn_limit"
REASON_TOKEN_BUDGET = "token_budget"
REASON_DEADLINE = "deadline"
REASON_JUDGE_UNRELIABLE = "judge_unreliable"
REASON_JUDGE_ERROR = "judge_error"
REASON_CANCELLED = "cancelled"

REASONS: frozenset[str] = frozenset(
    {
        REASON_OK,
        REASON_NO_IMPROVEMENT,
        REASON_TURN_LIMIT,
        REASON_TOKEN_BUDGET,
        REASON_DEADLINE,
        REASON_JUDGE_UNRELIABLE,
        REASON_JUDGE_ERROR,
        REASON_CANCELLED,
    }
)

# 系统提示词（JSON 契约的唯一说明处：模型只知道这一个协议）
#
# 「逐句润色 / 保持句子结构与出现顺序」这一条**不是**修辞偏好 —— 它来自
# `SYSTEM_WRITING_POLISH_PROMPT`（一次性润色时代，2026-08-21 加入）的实测结论：
# `/api/writing/ai-polish/diff` 的 hunk 是**按句对齐**的（`essay_diff.diff_sentences`），
# 模型一旦合并或拆分句子，diff 就会退化成「整段删除 + 整段新增」⇒ 前端逐 hunk
# 采纳/保留的 UI 失去可操作的粒度。循环形态下这条约束同样必须存在（收尾那一轮
# 吐的就是 `corrected_text`），故从旧提示词原样并入。
POLISH_LOOP_SYSTEM_PROMPT = (
    "你是德语（歌德 A1）写作润色助手。每一轮**只**回复一个 JSON 对象，不要输出任何其他文字。\n"
    "回复有且只有两种形态：\n"
    '1) 还需要证据：{"tool_call": {"name": "<工具名>", "payload": {...}}}\n'
    '2) 可以收尾：{"corrected_text": "<润色后的全文>", "notes_zh": ["<中文说明>", ...]}\n'
    "工具名必须在可用工具列表里，否则会被拒绝并把错误原样回传给你。\n"
    "请尽量逐句润色，保持句子的结构与出现顺序，不要合并或拆分句子，除非确实必要。\n"
    "收尾前请自查 A1 硬规则：称呼语存在且以逗号结尾、逗号后正文首词小写、结语后不得加逗号。"
)


@dataclass(frozen=True)
class Budget:
    """循环级预算（D2：轮次上界 + token 总量 + 墙钟 deadline）。

    - `max_turns`：轮次硬闸（与 token/deadline 并列，不是"兜底"）；
    - `max_tokens_total`：**completion token 累计**上界（与 `max_tokens` 同单位）；
    - `deadline_s`：墙钟上界，MUST 严格小于外层请求超时（到点次序）。
    """

    max_turns: int = MAX_TURNS_DEFAULT
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    deadline_s: float = DEFAULT_DEADLINE_S


@dataclass(frozen=True)
class LoopResult:
    """循环出口契约（Task 6 直接搬进响应体的 `converged` / `unconverged_reason`）。

    `violations` 是**返回文本**的违规清单（不是最后一轮的），便于前端逐条显示。
    """

    text: str
    converged: bool
    reason: str | None
    rounds: int
    violations: list[dict[str, Any]]


# ── 计量 / 抽取 / 截断（都是纯函数，便于单测与预算实测复用） ────────────────────
def estimate_tokens(s: str) -> int:
    """字符折算估算 token 数（**UNVERIFIED 假设**，见 `CHARS_PER_TOKEN_ESTIMATE`）。"""
    return math.ceil(len(s) / CHARS_PER_TOKEN_ESTIMATE)


def completion_tokens_of(reply: dict[str, Any]) -> int:
    """取一次回复的 completion token 数：优先 `usage.completion_tokens`，缺失则估算。

    两条路径都必须存在且各自有测试：真链路将来会带 `usage`（精确），今天只有估算。
    """
    usage = reply.get("usage")
    if isinstance(usage, dict):
        raw = usage.get("completion_tokens")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return int(raw)
    return estimate_tokens(_dump(reply))


def default_violations_of(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """默认违规抽取器：**只取 `level == "error"`**（warning 不算）。

    理由：`analyze_a1_email` 的 `warning` 是**建议**（字数偏短/偏多、称呼语缺逗号…），
    不构成"不达标"；只有 `error`（缺称呼语 / 逗号后正文首词大写 / 结语加逗号）才阻止收敛。
    若把 warning 也算违规，几乎所有 A1 短文都永远 `v > 0` ⇒ 循环**永不收敛**，
    `no_improvement` 变恒真 —— 那才是真正的静默失败。
    """
    out: list[dict[str, Any]] = []
    if not isinstance(verdict, dict):
        return out
    suggestions = verdict.get("suggestions", [])
    if not isinstance(suggestions, list):
        return out
    for item in suggestions:
        if isinstance(item, dict) and item.get("level") == "error":
            out.append(item)
    return out


def truncate_evidence(
    text: str,
    *,
    max_lines: int = EVIDENCE_MAX_LINES,
    max_bytes: int = EVIDENCE_MAX_BYTES,
) -> str:
    """证据注入前的**双限**截断：先限行数、再限 UTF-8 字节（两个限都真起作用）。"""
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    out = "\n".join(lines)
    raw = out.encode("utf-8")
    if len(raw) > max_bytes:
        # 按字节切段后 `errors="ignore"` 丢弃尾部半个多字节字符，不产生非法 UTF-8。
        out = raw[:max_bytes].decode("utf-8", errors="ignore")
    return out


def _dump(obj: Any) -> str:
    """确定性序列化（`sort_keys` ⇒ 同输入同输出，token 估算才可复现）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _render_evidence(result: dict[str, Any]) -> str:
    """把工具结果渲染成多行文本（列表值逐项一行 ⇒ 行数上限才有意义）。"""
    lines: list[str] = []
    for key in sorted(result):
        value = result[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item if isinstance(item, str) else _dump(item)}")
        else:
            lines.append(f"{key}: {value if isinstance(value, str) else _dump(value)}")
    return "\n".join(lines)


def _brief(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _default_judge(text: str, leitpunkte: list[str] | None) -> dict[str, Any]:
    """默认裁判 = `writing.analyze_a1_email`（确定性规则引擎，不出网）。"""
    return analyze_a1_email(text, leitpunkte)


async def _call_judge(
    fn: Callable[[str, list[str] | None], Any],
    text: str,
    leitpunkte: list[str] | None,
) -> Any:
    """调一次裁判：**同步裁判移出事件循环**（Task 8 接缝②）。

    为什么必须绕这一层（两处调用点都走它）：

    1. **长裁判不阻塞同进程其它路由**：`analyze_a1_email` 是同步 CPU/IO 活，直接跑在
       事件循环上会把 `/api/health` 与其它路由一起按在地上（实测单次可达数百 ms）；
    2. **取消可掐断**：跑在事件循环上时 `task.cancel()` 递不进去（取消要等协程让出
       控制权，而同步函数不让）⇒ Task 6 的取消按钮对「在途裁判」无效。
       `asyncio.to_thread` 的等待点可取消：任务立刻收到 `CancelledError`，
       循环**不再等待**那个线程（线程本身掐不断，这是 asyncio 的既有语义）。

    `iscoroutinefunction` 那一支**必须有**：注入方给了 async 裁判时，`to_thread`
    只会把 **coroutine 对象**当返回值交回来 ⇒ 上层拿到「没有裁决」⇒ 违规数恒 0
    ⇒ 循环静默假收敛（最危险的失败形态）。
    """
    if inspect.iscoroutinefunction(fn):
        return await fn(text, leitpunkte)
    return await asyncio.to_thread(fn, text, leitpunkte)


def _make_default_dispatch(
    tools_map: Mapping[str, Callable[..., Awaitable[dict[str, Any]]]],
) -> Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]:
    """默认分发器：同进程直调白名单工具；**未知工具名 ⇒ errors-as-messages，不抛异常**。"""

    async def _dispatch(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        fn = tools_map.get(name)
        if fn is None:
            return {"error": f"未知工具 '{name}'", "available": sorted(tools_map)}
        return await fn(payload)

    return _dispatch


def _emit(on_progress: Callable[[dict[str, Any]], None] | None, event: dict[str, Any]) -> None:
    if on_progress is None:
        return
    on_progress(event)


async def run_polish_loop(
    *,
    text: str,
    leitpunkte: list[str] | None = None,
    tools: Mapping[str, Callable[..., Awaitable[dict[str, Any]]]] | None = None,
    budget: Budget = Budget(),
    chat: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    judge: Callable[[str, list[str] | None], dict[str, Any]] | None = None,
    violations_of: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    dispatch: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]] | None = None,
    clock: Callable[[], float] = time.monotonic,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> LoopResult:
    """跑一遍有界润色循环。**全部依赖可注入**（测试一律 stub，严禁真 Key）。

    返回 `LoopResult`：未收敛 MUST 带原因码（零静默失败），`rounds` 是真实跑过的轮数。
    """
    tools_map: Mapping[str, Callable[..., Awaitable[dict[str, Any]]]] = tools or {}
    judge_fn: Callable[[str, list[str] | None], dict[str, Any]] = judge if judge is not None else _default_judge
    violations_fn = violations_of if violations_of is not None else default_violations_of
    dispatch_fn = dispatch if dispatch is not None else _make_default_dispatch(tools_map)
    chat_fn: Callable[..., Awaitable[dict[str, Any]]] = chat if chat is not None else llm_client.chat
    # 注入 chat 时不读配置（测试不该碰数据库）；真链路才需要模型名。
    model = "" if chat is not None else get_effective_api_model()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": POLISH_LOOP_SYSTEM_PROMPT},
        {"role": "user", "content": f"待润色的德语文本:\n{text}"},
    ]
    if tools_map:
        messages.append({"role": "user", "content": "可用工具: " + ", ".join(sorted(tools_map))})
    if leitpunkte:
        messages.append({"role": "user", "content": "Leitpunkte: " + " / ".join(leitpunkte)})

    # 历史候选 `(文本, 违规数, 违规清单)` —— 不降即停时回退到 argmin。
    history: list[tuple[str, int, list[dict[str, Any]]]] = []
    prev_v: int | None = None
    degraded: str | None = None

    # v_0：先裁一次原文，给停止策略一个可比较的基线（裁判异常 ⇒ 单轮降级，不冒泡）。
    try:
        baseline_violations = violations_fn(await _call_judge(judge_fn, text, leitpunkte))
        prev_v = len(baseline_violations)
        history.append((text, prev_v, baseline_violations))
    except Exception as exc:  # 宽捕是刻意的：errors-as-messages，任何裁判异常都不得冒泡
        degraded = REASON_JUDGE_ERROR
        messages.append({"role": "user", "content": f"[裁判异常] {_brief(exc)}"})

    rounds = 0
    tokens_used = 0
    judged_candidates = 0
    converged = False
    # 收敛候选 `(文本, 违规清单)`：只有被判为零违规的收尾候选才配记在这里 ——
    # 收敛时的文本归属是**它**，不是出口的 argmin（理由见出口处注释）。
    converged_candidate: tuple[str, list[dict[str, Any]]] | None = None
    reason: str | None = None
    t0 = clock()

    while rounds < budget.max_turns:
        # ① 取消（Task 6 的取消按钮靠它）
        if should_stop is not None and should_stop():
            reason = REASON_CANCELLED
            break
        # ② 预算前置检查（**每轮开始之前**）：deadline 先于 token，剩余 ≤0 直接退出
        remaining = budget.deadline_s - (clock() - t0)
        if remaining <= 0:
            reason = REASON_DEADLINE
            break
        if tokens_used >= budget.max_tokens_total:
            reason = REASON_TOKEN_BUDGET
            break

        rounds += 1
        # 到点次序：内层 timeout 取 min(每轮默认超时, 剩余 deadline)
        per_call_timeout = min(DEFAULT_PER_CALL_TIMEOUT_S, remaining)
        per_call_cap = min(llm_client.DEFAULT_MAX_TOKENS, budget.max_tokens_total - tokens_used)
        verdict_this_round: dict[str, Any] | None = None

        raw_reply = await chat_fn(
            messages=list(messages),
            model=model,
            timeout=per_call_timeout,
            max_tokens=per_call_cap,
            response_format=llm_client.JSON_OBJECT,
        )
        tokens_used += completion_tokens_of(raw_reply if isinstance(raw_reply, dict) else {})

        if not isinstance(raw_reply, dict):
            messages.append({"role": "user", "content": "[模型回复格式不合法] 必须是 JSON 对象"})
            _emit(
                on_progress,
                {
                    "round": rounds,
                    "max_turns": budget.max_turns,
                    "event": "bad_reply",
                    "tokens_used": tokens_used,
                    "elapsed": clock() - t0,
                },
            )
            continue

        # ── 二值判断（D1 / Unknown C） ────────────────────────────────────────
        tool_call = raw_reply.get("tool_call")
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
            payload = tool_call.get("payload")
            if not isinstance(name, str) or not isinstance(payload, dict):
                messages.append(
                    {"role": "user", "content": "[工具调用格式不合法] 需要 {'name': str, 'payload': {}}"}
                )
                _emit(
                    on_progress,
                    {
                        "round": rounds,
                        "max_turns": budget.max_turns,
                        "event": "bad_tool_call",
                        "tokens_used": tokens_used,
                        "elapsed": clock() - t0,
                    },
                )
                continue
            # 工具自身抛异常同样 errors-as-messages（不炸循环）
            # 接缝①：dispatch 也 MUST 有超时。剩余 deadline 在**调用前重算**（不能复用
            # 轮首那个：本轮的 chat 已经花掉时间），口径与 chat 完全一致 ——
            # min(每轮默认超时, 剩余 deadline)。剩余 ≤0 ⇒ timeout=0 ⇒ `wait_for` 立刻
            # 超时，同样喂回模型；下一轮轮首的预算前置检查会以 `deadline` 原因码收口。
            remaining_now = budget.deadline_s - (clock() - t0)
            dispatch_timeout = min(DEFAULT_PER_CALL_TIMEOUT_S, max(remaining_now, 0.0))
            try:
                result = await asyncio.wait_for(dispatch_fn(name, payload), timeout=dispatch_timeout)
            except asyncio.TimeoutError:
                # 超时是"证据"不是异常：喂回模型让它换招，循环不炸、不冒泡。
                result = {"error": f"工具 '{name}' 执行超时（>{dispatch_timeout:.1f}s）"}
            except Exception as exc:  # 宽捕是刻意的：工具失败是"证据"，不是 500
                result = {"error": f"工具 '{name}' 执行失败: {_brief(exc)}"}
            evidence = truncate_evidence(_render_evidence(result))
            messages.append({"role": "user", "content": f"[工具结果:{name}]\n{evidence}"})
            _emit(
                on_progress,
                {
                    "round": rounds,
                    "max_turns": budget.max_turns,
                    "event": "tool",
                    "tool": name,
                    "tokens_used": tokens_used,
                    "elapsed": clock() - t0,
                },
            )
            continue

        # ── 收尾候选 ──────────────────────────────────────────────────────────
        candidate = raw_reply.get("corrected_text")
        if not isinstance(candidate, str) or not candidate:
            candidate = text  # 缺失则回退原文（不是"什么都不做"，是有明确候选）

        # ③ D3 收尾终审守卫：无本轮新鲜裁决 ⇒ 驳回"直接收尾"，强制补跑一次裁判。
        #    删掉这个守卫 ⇒ 裁判被跳过 ⇒ v_n 恒 0 ⇒ 循环**静默假收敛**（最危险的失败形态）。
        if verdict_this_round is None:
            try:
                verdict_this_round = await _call_judge(judge_fn, candidate, leitpunkte)
            except Exception as exc:  # 宽捕是刻意的：Unknown D 按"会抛"设计 ⇒ 单轮降级
                degraded = REASON_JUDGE_ERROR
                messages.append({"role": "user", "content": f"[裁判异常] {_brief(exc)}"})
                _emit(
                    on_progress,
                    {
                        "round": rounds,
                        "max_turns": budget.max_turns,
                        "event": "judge_error",
                        "tokens_used": tokens_used,
                        "elapsed": clock() - t0,
                    },
                )
                continue
        if not isinstance(verdict_this_round, dict):
            # 裁判给不出裁决对象 ⇒ 与哨兵同码：都是"裁判不可信"
            reason = REASON_JUDGE_UNRELIABLE
            break

        violations = violations_fn(verdict_this_round)
        v = len(violations)
        judged_candidates += 1
        history.append((candidate, v, violations))
        _emit(
            on_progress,
            {
                "round": rounds,
                "max_turns": budget.max_turns,
                "event": "judged",
                "violations": v,
                "tokens_used": tokens_used,
                "elapsed": clock() - t0,
            },
        )

        # ④ 收敛 / 停止策略 / 哨兵
        if v == 0:
            # 收敛 ⇒ 把这个候选记为收敛候选：循环出口的文本归属就是**它**
            # （为什么不能再走出口的 argmin，见出口处注释）。
            converged = True
            reason = REASON_OK
            converged_candidate = (candidate, violations)
            break
        if prev_v is not None:
            # 哨兵：裁判不再下降（v_n == v_{n-1} 且 n>=2）⇒ 裁判不可信
            if v == prev_v and judged_candidates >= 2:
                reason = REASON_JUDGE_UNRELIABLE
                break
            # 运行时策略：不降即停
            if v >= prev_v:
                reason = REASON_NO_IMPROVEMENT
                break
        prev_v = v

    if reason is None:
        reason = REASON_TURN_LIMIT
    if reason == REASON_TURN_LIMIT and degraded is not None:
        reason = degraded  # 轮次耗尽只是表象，真实原因是裁判一直在抛

    if converged_candidate is not None:
        # 收敛 ⇒ 返回那个被判为零违规的候选（`converged_candidate` 与 `converged`
        # 同生同灭：只有上面的收敛分支会写它）。
        # 为什么收敛不能再走 argmin：`min` 在并列时取**最早**条目 = 原文，而
        # v_0 == v_1 == 0 是常态（适用性闸门下裁判对非书信体无话可说）⇒ argmin
        # 会把用户点的润色原样退回，与循环自己「已收敛」的结论自相矛盾。
        best_text, best_violations = converged_candidate
    elif history:
        # 未收敛 ⇒ 仍走 argmin 回退（Task 4 钉死的语义：`no_improvement` 回退
        # 原文是特性，不是缺陷）。
        best = min(history, key=lambda item: item[1])
        best_text, _, best_violations = best
    else:
        best_text, best_violations = text, []

    _emit(
        on_progress,
        {
            "event": "done",
            "round": rounds,
            "max_turns": budget.max_turns,
            "converged": converged,
            "reason": reason,
            "violations": len(best_violations),
            "tokens_used": tokens_used,
            "elapsed": clock() - t0,
        },
    )
    return LoopResult(
        text=best_text,
        converged=converged,
        reason=reason,
        rounds=rounds,
        violations=best_violations,
    )
