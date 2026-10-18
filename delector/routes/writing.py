# -*- coding: utf-8 -*-
"""写作工坊域路由：写作批改、AI 润色、作文 CRUD、版本链与写作卡片。"""

# mypy: disable-error-code="misc,untyped-decorator"

import asyncio
import contextlib
import functools
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, NamedTuple, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from delector.core.database import (
    _require_localhost,
    db_conn,
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
)
from delector.nlp_engine import processor as _nlp_processor
from delector.nlp_engine.processor import nlp
from delector.routes.cards import (
    GrammarCardReq,
    add_grammar_card,
)
from delector.services import llm_client, polish_loop
from delector.services.writing import analyze_a1_email, collect_violations
from delector.tools.polish import POLISH_TOOL_ALLOWLIST, call_tool

router = APIRouter()


class WritingAnalyzeReq(BaseModel):
    text: str


class EssayCreateReq(BaseModel):
    title: str
    content: str


class EssayUpdateReq(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class WritingCardReq(BaseModel):
    essay_id: int
    sentence_id: int
    span_index: int


class AIPolishReq(BaseModel):
    text: str
    # 默认关 ⇒ 既有 JSON 行为与既有测试逐字不变（响应体只新增 converged 两字段）。
    # 打开后返回 SSE（逐轮进度 + 取消），见 `_polish_event_stream`。
    stream: bool = False


class WritingApplyReq(BaseModel):
    essay_id: int
    original_text: str
    corrected_text: str
    accepted_indices: List[int]


class EssayVersionCreateReq(BaseModel):
    message: Optional[str] = "手动保存"


class EssayRestoreReq(BaseModel):
    version_id: int


# ── AI 润色：有界循环（Task 6）——适用性闸门 / 录制包装 / SSE ─────────────────
# 端点层原因码：循环**根本没跑**（无 API Key），不是循环的任何一种结局 ⇒ **不进**
# `polish_loop.REASONS`（加进去会让「原因码集合 = 循环的出口」这条契约失真）。
REASON_NO_API_KEY = "no_api_key"

# SSE 的断连探活间隔。`request.is_disconnected()` 在 starlette 1.6 是**非阻塞**的
# （内部用一个已取消的 anyio CancelScope 包住 receive()：没有排队消息就立刻返回 False），
# 所以可以在生成器的每一圈安全轮询，不会挂住流。
_SSE_POLL_INTERVAL_S = 0.02

# 格式/字数族 = 书信题材专属规则的 rule 前缀（`a1_*`：称呼语 / 结语 / 字数）。
# 语法族 = 不以 `a1_` 开头的 rule（artikel / kasus / praeposition / numerus / rektion /
# wortstellung）—— **与题材无关** ⇒ 对任意德语文本生效（Task 7 收窄；`tempus` 是 advisory、
# 不进 `collect_violations` 的输出，天然不参与计数）。
_LETTER_FORMAT_RULE_PREFIX = "a1_"


def _text_kind(verdict: Dict[str, Any]) -> str:
    """文本族判定：**沿用既有 `greeting.valid` 口径**（书信体 ⇔ 称呼语合法）。

    ⚠️ 以 `greeting.valid` 为唯一判据的三条边界后果（**如实登记，勿删**）：

    ① **书信缺称呼语** ⇒ 归 `prose` ⇒ 格式族（含 `a1_greeting_missing` 这条 error）被
       `a1_` 前缀过滤 ⇒ 该类邮件的格式错**永远不被计数**；且提示词按初始文本族装配
       （`pick_system_prompt`）⇒ 走散文版。这是**继承自旧闸门**的边界，不是本批回归。
    ② **散文含称呼语** ⇒ 归 `letter` ⇒ 格式族照用（对散文生效）+ 书信版提示词。
    ③ **候选侧翻转（未收口欠账）**：循环的 kind **逐候选**按候选自身裁决体判定
       （`_polish_violations_of` 单参契约）⇒ 模型"删掉称呼语"的那个候选会翻转口径 ——
       该候选自身的格式族违规被过滤后 v 可能掉到 0。这是 2026-10-14 计划里已登记的
       "闸门对候选单向生效"欠账，本批**未收口**，如实登记。
    """
    greeting = verdict.get("greeting") if isinstance(verdict, dict) else None
    if isinstance(greeting, dict) and greeting.get("valid"):
        return "letter"
    return "prose"


def violations_for(kind: str, verdict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """适用性闸门（**Task 7 收窄版**：按**规则族**分流，而不是按整份裁判开关）。

    - `kind == "letter"` ⇒ 格式/字数族（`a1_*`）+ 语法族 **全计**；
    - `kind == "prose"` ⇒ **只计语法族**（语法与题材无关）—— 这就是「循环的价值面扩到
      任意德语文本」的落点。

    统一抽取器：走 `collect_violations`（新键 `violations` 优先、legacy `suggestions` 回退，
    且只取 `level == "error"`），与裁判层同口径；advisory（warning 级）不在其输出里。

    ⚠️ **产品语义（ADR §10.3 失败模式的实际落点，MUST NOT 静默改）**：非书信文本的语法违规
    开始计数 ⇒ 若模型修不动（v 不降），循环按 Task 4 钉死的语义走 `no_improvement` ⇒ argmin
    回退**原文**（**不是**"首轮即接受"）。这是**明知而接受**的行为变更（2026-10-15 用户拍板）：
    价值面从"仅 A1 书信"扩到"任意德语文本"，代价是修不动的文本拿到原文 + 人话原因码
    （前端 `POLISH_REASON_COPY.no_improvement`）。

    历史注记（为什么不再"非书信体一律零违规"）：旧闸门是针对"裁判只有书信格式规则"的权宜
    —— 当时 `a1_greeting_missing` 对每篇非书信文本恒报 error ⇒ v 恒 > 0 ⇒ 恒回退原文。
    语法维度接线后前提变了：上面的失败模式只在**模型真修不动**时出现，而不是对非书信文本恒真。
    """
    violations = collect_violations(verdict)
    if kind == "letter":
        return violations
    return [v for v in violations if not str(v.get("rule", "")).startswith(_LETTER_FORMAT_RULE_PREFIX)]


def _polish_violations_of(verdict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """循环入口（单参，`violations_of` 契约）：文本族由**裁决体自己**判（沿用 `greeting.valid`）。"""
    return violations_for(_text_kind(verdict), verdict)


# 散文向系统提示词（Task 7 的立论冲突解法 b：提示词按**文本族**参数化，业务知识住产品层）。
# 与书信版（内核 `polish_loop.POLISH_LOOP_SYSTEM_PROMPT`）的差异——**只删题材指令，不动协议**：
# - 去掉逐字的 A1 书信自查指令（"称呼语存在且以逗号结尾 / 逗号后正文首词小写 / 结语后不得加
#   逗号"）：评审黄卡 #2 —— 对非书信文本它会**诱导模型加一个称呼语**，而格式族规则此时已被
#   闸门关掉 ⇒ 污染无守卫；
# - **保留** JSON 契约（循环按它解析回复）与"逐句润色、保持句子结构与出现顺序"（来自
#   `essay_diff.diff_sentences` 的按句对齐，diff 逐 hunk 采纳 UI 的**关键约束**）。
POLISH_PROSE_SYSTEM_PROMPT = (
    "你是德语写作润色助手。每一轮**只**回复一个 JSON 对象，不要输出任何其他文字。\n"
    "回复有且只有两种形态：\n"
    '1) 还需要证据：{"tool_call": {"name": "<工具名>", "payload": {...}}}\n'
    '2) 可以收尾：{"corrected_text": "<润色后的全文>", "notes_zh": ["<中文说明>", ...]}\n'
    "工具名必须在可用工具列表里，否则会被拒绝并把错误原样回传给你。\n"
    "请尽量逐句润色，保持句子的结构与出现顺序，不要合并或拆分句子，除非确实必要。"
)


def pick_system_prompt(kind: str) -> str:
    """文本族 → 系统提示词（Task 7；**业务知识住在产品层**，内核只收参数）。

    - `"letter"` ⇒ 既有 A1 书信提示词（`polish_loop.POLISH_LOOP_SYSTEM_PROMPT`，逐字）；
    - 其余（`"prose"` 及未知值）⇒ 散文向提示词 —— 未知 kind 取散文向是**保守默认**：
      宁少一条题材指令（漏掉书信自查），也不冒"对非书信文本诱导加称呼语"的污染风险。
    """
    if kind == "letter":
        return polish_loop.POLISH_LOOP_SYSTEM_PROMPT
    return POLISH_PROSE_SYSTEM_PROMPT


def _make_tool_audit_hook(seen: List[str]) -> Any:
    """润色工具的前置钩子：**权限闸 + 审计留痕**（Task 5 的 hooks 面，每次请求新建）。

    权限闸在这里再挡一次白名单（纵深防御）：`call_tool` 内部已有同名兜底，但钩子
    是「调用之前」的唯一挂点，把「能力面」检查放在这里才不会被 dispatcher 的实现
    细节带着走。钩子抛异常 ⇒ 该次调用被拒（errors-as-messages，不炸循环）。
    """

    def _audit(name: str, _payload: Dict[str, Any]) -> None:
        if name not in POLISH_TOOL_ALLOWLIST:
            raise PermissionError(f"工具 '{name}' 不在润色白名单内")
        seen.append(name)

    return _audit


class _PolishReplyRecorder:
    """`llm_client.chat` 的**录制包装**：从每一轮回复里捕获最后的 `notes_zh` /
    `error_count`，再原样返回。

    为什么端点要自己录、而不是直接用 `LoopResult` 的字段：`error_count` 今天的语义是
    **模型报的数**（`tests/test_server.py::test_ai_polish_diff_mocked` 的
    `error_count == 2` 就来自模型回复）。改成裁判口径会**静默破坏既有断言**，故原样
    记录：模型给了就用模型的；没给回退 `len(notes_zh)`；再没有才回退 `len(violations)`。

    本包装**不碰文本归属**：收敛 ⇒ 返回那个零违规候选；未收敛 ⇒ argmin 回退，这个
    结论由循环自己给出（`polish_loop.run_polish_loop` 出口）。端点曾按
    `last_corrected_text` 兜底，但 recorder 分不清「收尾候选轮」与「取证轮」——
    模型在取证轮回个 `corrected_text`（协议外字段）就会被误当成采纳文本，故删掉。

    `model` 由本包装自己取真身：循环在**注入 chat** 时不读配置（测试不该碰数据库），
    传进来的 `model` 是空串。
    """

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.notes_zh: List[str] = []
        self.error_count: Optional[int] = None
        self.usage: Optional[Dict[str, int]] = None

    async def __call__(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str,
        timeout: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        reply = await llm_client.chat(
            messages=messages,
            model=get_effective_api_model(),
            timeout=timeout,
            max_tokens=max_tokens,
            response_format=response_format,
            include_usage=True,
            api_key=self._api_key,
            base_url=self._base_url,
        )
        self._capture(reply)
        return reply

    def _capture(self, reply: Any) -> None:
        if not isinstance(reply, dict):
            return
        notes = reply.get("notes_zh")
        if isinstance(notes, list):
            self.notes_zh = [str(item) for item in notes]
        count = reply.get("error_count")
        if isinstance(count, int) and not isinstance(count, bool):
            self.error_count = count
        usage = reply.get("usage")
        if isinstance(usage, dict):
            self.usage = {
                str(k): int(v)
                for k, v in usage.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }


def _make_judge(leitpunkte: Optional[List[str]], nlp: Any) -> Callable[[str], Dict[str, Any]]:
    """装配生产链路用的 **A1 裁判**（带 nlp）：内部调 `analyze_a1_email(text, leitpunkte, nlp)`。

    为什么必须由**产品层**装配、而不能用内核默认裁判：内核默认裁判是
    `polish_loop._default_judge` = `analyze_a1_email(text, leitpunkte)`（**不带 nlp**）⇒ 语法族
    恒不生效。能力必须在产品层装配，内核只保留「谁都能被注入」的缝（评审 RED#1 的闭环点）。

    降级语义边界（如实登记，勿删）：`nlp is None` 时本裁判只跑格式族、`judge_engine="rules_only"`；
    此时循环**照常收敛**（运行期 fail-open —— 禁止收敛会让 argmin 回退返回原文 = 功能报废）。
    “没检查语法”不等于“语法零违规”：声明层的诚实性由裁决体的 `judge_engine` 透出
    （`_JudgeRecorder` 捕获 → 响应体 `judge_degraded`），门禁层 fail-closed 由调用方承担。
    **禁止**靠塞一条人造 violation 来实现降级提示。

    ⚠️ **非书信文本的产品语义（Task 7 收窄后的落点；ADR §10.3 失败模式的实际发生点，勿删）**：
    本裁判对**任意德语文本**都会给出语法族裁决（语法与题材无关），闸门（`violations_for`）只把
    格式/字数族（`a1_*`）限给书信体。后果：非书信文本 + 语法错若**模型修不动**（候选的 v 不降），
    循环按 Task 4 钉死的语义走 `no_improvement` ⇒ argmin 回退**原文** ——
    **不是**"首轮即接受"，用户拿到原文 + 前端人话原因码（`no_improvement`）。
    这是 2026-10-15 用户拍板的**明知而接受**的行为（价值面从"仅 A1 书信"扩到"任意德语文本"）。
    """

    def _judge(text: str) -> Dict[str, Any]:
        return analyze_a1_email(text, leitpunkte, nlp)

    return _judge


class _JudgeRecorder:
    """裁判的**录制包装**（与 `_PolishReplyRecorder` 同形）：记下每次裁决的 `judge_engine`
    与 `judge_advisories`，再原样返回裁决。

    为什么端点要自己录：`judge_engine` / `advisories` 住在裁决体里（`analyze_a1_email` 的
    并列字段），而循环出口的 `LoopResult` 不带它们 ⇒ 端点必须从裁判这一侧捕获，才能把
    降级状态与 advisory **如实透出**到响应体（红线 1：不得让“没检查”看起来像“检查通过”；
    Task 6 HITL：warning 必须真能被看到，否则是 no-op）。

    `judge_advisories` 取裁决体 `advisories`（统一形状、`level=="warning"`）的 `message`
    文本；它**不进** `violations`（`violations_of`/`collect_violations` 只认 `level=="error"`）
    ⇒ 不改变 v、不阻断收敛。每次裁决**覆盖式**记录：记录的是**最后一次裁决**。

    ⚠️ 收窄说明（如实登记，勿删）：**argmin 回退路径下 `judge_advisories` 可能与出口文本
    不一致** —— 未收敛时循环出口走 `min(history, key=v)` 回退，出口文本可能是**更早**的
    候选或原文（`min` 并列取最早 ⇒ 此时原文胜出），而本包装记的是**最后一次裁判调用**的
    裁决 ⇒ 响应体 advisory 描述的是"最后一次被裁的文本"，不保证是返回给用户的那份。
    非阻断：advisory **不进任何计数**（v / 停止策略 / 收敛归属全不受它影响）⇒ 仅呈现层
    的对应性欠账。（`judge_engine` 是引擎装配态、与文本无关，不受此影响。）

    `__call__` 的第二参数兼容循环的 `judge_fn(text, leitpunkte)` 调用约定（leitpunkte 已由
    `_make_judge` 闭包绑定，这里忽略即可）。
    """

    def __init__(self, judge_fn: Callable[[str], Dict[str, Any]]) -> None:
        self._judge_fn = judge_fn
        # 未被裁过时的保守默认：宁报降级（rules_only）不报可用，避免“没跑却标成已跑”。
        self.judge_engine: str = "rules_only"
        self.judge_advisories: List[str] = []

    def __call__(self, text: str, leitpunkte: Optional[List[str]] = None) -> Dict[str, Any]:
        verdict = self._judge_fn(text)
        if isinstance(verdict, dict):
            engine = verdict.get("judge_engine")
            if isinstance(engine, str) and engine:
                self.judge_engine = engine
            advisories = verdict.get("advisories")
            if isinstance(advisories, list):
                self.judge_advisories = [str(a.get("message", "")) for a in advisories if isinstance(a, dict)]
        return verdict


class _PolishOutcome(NamedTuple):
    """一次润色的出口（端点据此组装响应体，流式与非流式共用一份）。

    `judge_engine`（追加，Task 1）：本次运行实际装配的裁判引擎（`"rules+spacy"` / `"rules_only"`），
    端据此算出响应体 `judge_degraded`。

    `judge_advisories`（追加，Task 6 HITL 收尾）：最后一次裁决的 advisory 文本（warning 级，
    当前 = B 维 `tempus`）——响应体 `judge_advisories` 的承载，**不参与任何计数**。
    """

    text: str
    notes_zh: List[str]
    error_count: int
    converged: bool
    reason: Optional[str]
    judge_engine: str
    judge_advisories: List[str]


def _no_key_outcome(text: str) -> _PolishOutcome:
    """无 API Key：**不走循环**，今日语义逐字保留（文本原样 + 提示去配 Key）。"""
    logging.warning("[writing/ai-polish] API Key not set — returning stub response.")
    return _PolishOutcome(
        text=text,
        notes_zh=["请在设置中配置 DeepSeek API Key 后使用 AI 润色功能"],
        error_count=0,
        converged=False,
        reason=REASON_NO_API_KEY,
        # 循环没跑 ⇒ 裁判也未装配 ⇒ 保守记为降级（宁报降级不报可用）。
        judge_engine="rules_only",
        judge_advisories=[],
    )


async def _run_polish(
    text: str,
    api_key: str,
    *,
    on_progress: Optional[Any] = None,
    should_stop: Optional[Any] = None,
) -> _PolishOutcome:
    """跑一遍润色循环：Task 4 内核 + Task 5 白名单/钩子 + **规则族闸门** + 语法裁判装配 +
    **文本族感知的提示词装配**。

    引擎来源（评审 RED#1 的闭环点）：先**只读**已加载模型（`get_loaded_nlp`，不触发加载/下载）；
    没有则在线程里尝试**仅本地**加载（`try_load_nlp_no_download` 绝不 `spacy.cli.download`，
    且同步函数放 `asyncio.to_thread` 里跑，不阻塞事件循环）。`nlp=None` ⇒ 裁判降级为
    `rules_only`、循环照常收敛，降级状态由 `judge_engine` 如实透出（响应体 `judge_degraded`）。

    文本族（Task 7）：`kind` 由**纯规则**裁决体判一次（见下方注释），决定
    ①系统提示词（`pick_system_prompt`：内核的 A1 书信指令对非书信体不适用）；
    ②闸门口径（`violations_for`：格式族只对书信体、语法族对任意德语文本）。

    产品语义（ADR §10.3 的落点，同款登记在 `violations_for` / `_make_judge` docstring）：
    非书信文本的语法违规**会计数** ⇒ 模型修不动时 `no_improvement` ⇒ argmin 回退**原文**
    （**不是**"首轮即接受"）。
    """
    seen: List[str] = []
    recorder = _PolishReplyRecorder(api_key, get_effective_api_base_url().rstrip("/"))
    # 引擎解析：先只读 → 再线程内本地加载（无下载）。绝不阻塞事件循环、绝不触发出网。
    nlp_loaded = _nlp_processor.get_loaded_nlp()
    if nlp_loaded is None:
        nlp_loaded = await asyncio.to_thread(_nlp_processor.try_load_nlp_no_download)
    # 文本族（选提示词用）：纯规则口径（不传 nlp ⇒ 不加载、不跑 spaCy）；`greeting.valid`
    # 本身是纯规则，与带 nlp 的裁决逐字一致。只用于装配提示词，不当作裁决（裁决仍由
    # judge_recorder 全量记录并透出）。
    kind = _text_kind(analyze_a1_email(text))
    judge_recorder = _JudgeRecorder(_make_judge(None, nlp_loaded))
    try:
        loop = await polish_loop.run_polish_loop(
            text=text,
            tools=POLISH_TOOL_ALLOWLIST,
            dispatch=functools.partial(call_tool, hooks=(_make_tool_audit_hook(seen),)),
            violations_of=_polish_violations_of,
            system_prompt=pick_system_prompt(kind),
            # 必须真的注入（不能退回内核默认裁判）—— 否则生产上语法裁判恒不生效 = dead-green。
            judge=judge_recorder,
            chat=recorder,
            budget=polish_loop.Budget(),
            text_type=kind,
            on_progress=on_progress,
            should_stop=should_stop,
        )
    except llm_client.LLMError as e:
        logging.error(f"[writing/ai-polish] DeepSeek API error: {e.detail} | raw: {e.raw[:200]}")
        raise HTTPException(status_code=502, detail=e.detail)
    if seen:
        logging.info("[writing/ai-polish] 工具调用: %s", ", ".join(seen))
    # 文本归属由循环自己给（Task 6 修订）：收敛 ⇒ 返回那个被判为零违规的候选；
    # 未收敛 ⇒ argmin 回退（Task 4 钉死的语义，`no_improvement` 回退原文是特性）。
    # 端点不再兜底：recorder 分不清「收尾候选轮」与「取证轮」，按 `corrected_text`
    # 兜底会把模型没被采用的文本当答案返回。
    final_text = loop.text
    error_count = recorder.error_count
    if error_count is None:
        error_count = len(recorder.notes_zh) if recorder.notes_zh else len(loop.violations)
    return _PolishOutcome(
        text=final_text,
        notes_zh=recorder.notes_zh,
        error_count=error_count,
        converged=loop.converged,
        reason=loop.reason,
        judge_engine=judge_recorder.judge_engine,
        judge_advisories=judge_recorder.judge_advisories,
    )


def _judge_degraded(outcome: _PolishOutcome) -> bool:
    """引擎降级标记（只增不改的响应字段）：`judge_engine != "rules+spacy"` ⇒ 语法族未启用。"""
    return outcome.judge_engine != "rules+spacy"


def _polish_payload(outcome: _PolishOutcome) -> Dict[str, Any]:
    """`/api/writing/ai-polish` 的 `result`（**只增不改**：追加 `judge_degraded` / `judge_advisories`）。"""
    return {
        "corrected_text": outcome.text,
        "notes_zh": outcome.notes_zh,
        "error_count": outcome.error_count,
        "converged": outcome.converged,
        "unconverged_reason": None if outcome.converged else outcome.reason,
        "judge_degraded": _judge_degraded(outcome),
        "judge_advisories": outcome.judge_advisories,
    }


def _polish_diff_payload(text: str, outcome: _PolishOutcome) -> Dict[str, Any]:
    """`/api/writing/ai-polish/diff` 的 `result`（既有字段与顺序一律不动，末尾追加 `judge_degraded` /
    `judge_advisories`）。"""
    from delector.services.essay_diff import diff_sentences

    return {
        "original": text,
        "corrected": outcome.text,
        "hunks": diff_sentences(text, outcome.text),
        "notes_zh": outcome.notes_zh,
        "error_count": outcome.error_count,
        "converged": outcome.converged,
        "unconverged_reason": None if outcome.converged else outcome.reason,
        "judge_degraded": _judge_degraded(outcome),
        "judge_advisories": outcome.judge_advisories,
    }


def _sse_frame(event: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


async def _polish_event_stream(*, request: Request, text: str, with_diff: bool) -> AsyncIterator[bytes]:
    """SSE：把循环的 `on_progress` 事件逐条吐出，最后一条是完整 `result`。

    取消：循环内每一圈探活，客户端已断开 ⇒ 置停止位（让循环自己收口）+ `task.cancel()`
    （掐断在途的那一次 chat，不再继续烧配额）后结束流。但这条轮询**赢不了**
    starlette 的 `listen_for_disconnect`（uvicorn HTTP scope spec_version='2.3' ⇒
    `StreamingResponse.__call__` 同时跑流与监听器，客户端断开时监听器抢先 cancel
    生成器）⇒ 外层再用 `try/finally` 兜底同步收尸，无论谁取消生成器在途 chat 都被掐断。
    """
    key = get_effective_api_key()
    if not key:
        # 无 Key 也走 SSE 形状（客户端只解析一种帧格式）：循环没跑，直接给 stub。
        outcome = _no_key_outcome(text)
        payload = _polish_diff_payload(text, outcome) if with_diff else _polish_payload(outcome)
        yield _sse_frame({"event": "result", "result": payload})
        return

    events: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    state = {"stop": False}

    async def _runner() -> _PolishOutcome:
        return await _run_polish(text, key, on_progress=events.put_nowait, should_stop=lambda: state["stop"])

    task = asyncio.ensure_future(_runner())
    try:
        while True:
            if await request.is_disconnected():
                state["stop"] = True
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return
            try:
                event = events.get_nowait()
            except asyncio.QueueEmpty:
                if task.done():
                    break
                await asyncio.sleep(_SSE_POLL_INTERVAL_S)
                continue
            yield _sse_frame(event)
            if event.get("event") == "done":
                break

        try:
            outcome = await task
        except HTTPException as e:
            # 流已经开了头（状态行已发出），改不了状态码 ⇒ 用一条 error 帧交代人话。
            yield _sse_frame({"event": "error", "detail": e.detail})
            return
        payload = _polish_diff_payload(text, outcome) if with_diff else _polish_payload(outcome)
        yield _sse_frame({"event": "result", "result": payload})
    finally:
        state["stop"] = True
        task.cancel()


@router.post("/api/writing/ai-polish")
async def api_writing_ai_polish(req: AIPolishReq, request: Request) -> Any:
    # P1-5 本机闸：循环有 key 时真实出网烧配额，理由同 /api/lookup/grammar。
    _require_localhost(request)
    text = req.text[:2000]
    if req.stream:
        return StreamingResponse(
            _polish_event_stream(request=request, text=text, with_diff=False),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    key = get_effective_api_key()
    outcome = _no_key_outcome(text) if not key else await _run_polish(text, key)
    return {"status": "ok", "result": _polish_payload(outcome)}


@router.post("/api/writing/ai-polish/diff")
async def api_writing_ai_polish_diff(req: AIPolishReq, request: Request) -> Any:
    # P1-5 本机闸（怀疑者复核时补的第五条）：内部同样走循环出网烧配额。
    _require_localhost(request)
    text = req.text[:2000]
    if req.stream:
        return StreamingResponse(
            _polish_event_stream(request=request, text=text, with_diff=True),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    key = get_effective_api_key()
    outcome = _no_key_outcome(text) if not key else await _run_polish(text, key)
    return {"status": "ok", "result": _polish_diff_payload(text, outcome)}


def _get_writer_nlp() -> Any:
    try:
        return nlp
    except Exception:
        return None


@router.post("/api/writing/analyze")
def api_writing_analyze(req: WritingAnalyzeReq) -> Any:
    from delector.services.writing import analyze_essay_text

    return analyze_essay_text(req.text[:2000], _get_writer_nlp())


@router.post("/api/essays")
def create_essay(req: EssayCreateReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    a = analyze_essay_text(req.content[:5000], _get_writer_nlp())
    cefr = a.get("cefr", {}).get("recommended_level")
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO essays "
            "(title, content, analysis_json, cefr_level, error_count, sentence_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (req.title, req.content, json.dumps(a, ensure_ascii=False), cefr, a["error_count"], len(a["sentences"])),
        )
        eid = cur.lastrowid
    return {
        "id": eid,
        "title": req.title,
        "content": req.content,
        "analysis_json": a,
        "error_count": a["error_count"],
    }


@router.get("/api/essays")
def list_essays() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, cefr_level, error_count, sentence_count, created_at, updated_at "
            "FROM essays ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/essays/{essay_id}")
def get_essay(essay_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    data = dict(row)
    if isinstance(data.get("analysis_json"), str):
        try:
            data["analysis_json"] = json.loads(data["analysis_json"])
        except Exception as exc:
            # Task 8b 真事故④：解析失败 MUST 留痕 —— 静默保持原始字符串会让响应形状（dict vs str）
            # 随数据质量悄悄变化，前端拿到两种形状却无人知。
            logging.getLogger("delector").warning(
                "essay #%s 的 analysis_json 解析失败（按原始字符串返回）：%s", essay_id, exc
            )
    return data


@router.put("/api/essays/{essay_id}")
def update_essay(essay_id: int, req: EssayUpdateReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        content = req.content if req.content is not None else row["content"]
        title = req.title if req.title is not None else row["title"]
        a = analyze_essay_text(content[:5000], _get_writer_nlp())
        now_str = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE essays SET title = ?, content = ?, analysis_json = ?, "
            "cefr_level = ?, error_count = ?, sentence_count = ?, updated_at = ? "
            "WHERE id = ?",
            (
                title,
                content,
                json.dumps(a, ensure_ascii=False),
                a.get("cefr", {}).get("recommended_level"),
                a["error_count"],
                len(a["sentences"]),
                now_str,
                essay_id,
            ),
        )
    return {"id": essay_id, "title": title, "content": content, "analysis_json": a, "error_count": a["error_count"]}


@router.delete("/api/essays/{essay_id}")
def delete_essay(essay_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        conn.execute("DELETE FROM essay_versions WHERE essay_id = ?", (essay_id,))
        conn.execute("DELETE FROM essays WHERE id = ?", (essay_id,))
    return {"status": "ok"}


@router.post("/api/writing/cards")
def save_writing_card(req: WritingCardReq) -> Any:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (req.essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    raw_analysis = row["analysis_json"]
    try:
        a = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
    except Exception:
        a = {}
    if not isinstance(a, dict):
        a = {}
    sentences = a.get("sentences", [])
    if not isinstance(sentences, list) or req.sentence_id < 0 or req.sentence_id >= len(sentences):
        raise HTTPException(400, "sentence_id 越界")
    sent = sentences[req.sentence_id]
    if not isinstance(sent, dict):
        raise HTTPException(400, "sentence_id 越界")
    spans = sent.get("spans", [])
    if not isinstance(spans, list) or req.span_index < 0 or req.span_index >= len(spans):
        raise HTTPException(400, "span_index 越界")
    sp = spans[req.span_index]
    if not isinstance(sp, dict):
        raise HTTPException(400, "span_index 越界")
    sentence_text = sent.get("text", "")
    card = GrammarCardReq(
        article_id=None,
        sentence_context=sentence_text,
        grammar_name=f"写作润色 · {sp.get('error_type', '')}",
        cefr_level=row["cefr_level"] or "B1",
        explanation_zh=sp.get("explanation_zh", ""),
        rule_formula=sp.get("corrected_form", ""),
        corrected_form=sp.get("corrected_form", ""),
        error_type=sp.get("error_type", ""),
    )
    return add_grammar_card(card)


@router.post("/api/essays/{essay_id}/versions")
def save_essay_version(essay_id: int, req: EssayVersionCreateReq) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        msg = req.message.strip() if (req.message and req.message.strip()) else "手动保存"
        cur = conn.execute(
            "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
            (essay_id, row["content"], row["analysis_json"], msg),
        )
        version_id = cur.lastrowid
        created_row = conn.execute("SELECT created_at FROM essay_versions WHERE id = ?", (version_id,)).fetchone()
        created_at = created_row["created_at"] if created_row else datetime.utcnow().isoformat()
    return {"version_id": version_id, "message": msg, "created_at": created_at}


@router.get("/api/essays/{essay_id}/versions")
def list_essay_versions(essay_id: int) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        rows = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE essay_id = ? ORDER BY id DESC",
            (essay_id,),
        ).fetchall()
        result = []
        for r in rows:
            raw_a = r["analysis_json"]
            try:
                a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a
                err_count = a.get("error_count", 0) if isinstance(a, dict) else 0
            except Exception:
                err_count = 0
            result.append(
                {
                    "id": r["id"],
                    "essay_id": r["essay_id"],
                    "message": r["message"],
                    "created_at": r["created_at"],
                    "error_count": err_count,
                }
            )
    return result


@router.get("/api/essays/{essay_id}/versions/{version_id}")
def get_essay_version(essay_id: int, version_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE id = ? AND essay_id = ?",
            (version_id, essay_id),
        ).fetchone()
        if not v:
            raise HTTPException(404, "version not found")
        raw_a = v["analysis_json"]
        try:
            a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a
            err_count = a.get("error_count", 0) if isinstance(a, dict) else 0
        except Exception:
            a = None
            err_count = 0
    return {
        "id": v["id"],
        "essay_id": v["essay_id"],
        "message": v["message"],
        "created_at": v["created_at"],
        "content": v["content"],
        "analysis_json": a,
        "error_count": err_count,
    }


@router.delete("/api/essays/{essay_id}/versions/{version_id}")
def delete_essay_version(essay_id: int, version_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    with db_conn() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id FROM essay_versions WHERE id = ? AND essay_id = ?", (version_id, essay_id)
        ).fetchone()
        if not v:
            raise HTTPException(404, "version not found")
        conn.execute("DELETE FROM essay_versions WHERE id = ? AND essay_id = ?", (version_id, essay_id))
    return {"status": "ok", "deleted_version_id": version_id}


@router.post("/api/essays/{essay_id}/restore")
def restore_essay_version(essay_id: int, req: EssayRestoreReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    with db_conn() as conn:
        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        version = conn.execute(
            "SELECT * FROM essay_versions WHERE id = ? AND essay_id = ?", (req.version_id, essay_id)
        ).fetchone()
        if not version:
            raise HTTPException(404, "version not found")

        checkpoint_version_id = None
        if version["content"] != essay["content"]:
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
                (essay_id, essay["content"], essay["analysis_json"], f"恢复到版本 {req.version_id} 之前"),
            )
            checkpoint_version_id = cur.lastrowid
            a = analyze_essay_text(version["content"][:5000], _get_writer_nlp())
            now_str = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE essays SET content = ?, analysis_json = ?, cefr_level = ?, "
                "error_count = ?, sentence_count = ?, updated_at = ? WHERE id = ?",
                (
                    version["content"],
                    json.dumps(a, ensure_ascii=False),
                    a.get("cefr", {}).get("recommended_level"),
                    a["error_count"],
                    len(a["sentences"]),
                    now_str,
                    essay_id,
                ),
            )
        else:
            raw_a = essay["analysis_json"]
            a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a

    return {
        "id": essay_id,
        "content": version["content"],
        "analysis_json": a,
        "error_count": a["error_count"],
        "checkpoint_version_id": checkpoint_version_id,
    }


@router.post("/api/writing/apply")
def api_writing_apply(req: WritingApplyReq) -> Dict[str, Any]:
    from delector.services.essay_diff import diff_sentences, merge_sentences
    from delector.services.writing import analyze_essay_text

    hunks = diff_sentences(req.original_text, req.corrected_text)
    if any(idx < 0 or idx >= len(hunks) for idx in req.accepted_indices):
        raise HTTPException(400, "accepted_indices 越界")

    accepted = [i in set(req.accepted_indices) for i in range(len(hunks))]
    merged = merge_sentences(req.original_text, req.corrected_text, accepted)

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (req.essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")

        if req.accepted_indices and merged != row["content"]:
            a = analyze_essay_text(merged[:5000], _get_writer_nlp())
            now_str = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE essays SET title = ?, content = ?, analysis_json = ?, "
                "cefr_level = ?, error_count = ?, sentence_count = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    row["title"],
                    merged,
                    json.dumps(a, ensure_ascii=False),
                    a.get("cefr", {}).get("recommended_level"),
                    a["error_count"],
                    len(a["sentences"]),
                    now_str,
                    req.essay_id,
                ),
            )
            msg = f"AI 润色 · 接受 {len(req.accepted_indices)}/{len(hunks)} 处"
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
                (req.essay_id, merged, json.dumps(a, ensure_ascii=False), msg),
            )
            version_id = cur.lastrowid
        else:
            version_id = None
            raw_analysis = row["analysis_json"]
            a = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
            merged = row["content"]

    return {
        "content": merged,
        "analysis_json": a,
        "error_count": a["error_count"],
        "version_id": version_id,
    }
