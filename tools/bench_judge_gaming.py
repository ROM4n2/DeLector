# -*- coding: utf-8 -*-
"""§4.3 第 8 条对照实验的三臂 harness 骨架（Task 2；**零 Key / `--dry-run` 可跑**）。

为什么存在
----------
计划 `docs/plans/2026-10-15-judge-gaming-experiment.md` 的 Task 2：把设计稿
`docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` §3/§4 的三臂对照
落成**可复跑的确定性骨架**。本文件只负责「按三臂跑、如实记录」——判决量的数学在
Task 3、盲评 rater 在 Task 4、真跑（HITL）在 Task 5/6。**不接线、不改生产代码路径**：
只经 `run_polish_loop` 的注入缝复用生产链路（chat / tools / budget / judge /
violations_of / system_prompt / on_progress），不改内核语义。

三臂定义（MUST 与设计稿 §4 表格逐条一致）
---------------------------------------
- **A1 基线**：`Budget(max_turns=1)`（等价于今日的一次性润色）；
- **A2 迭代无信号**：`Budget(max_turns=3)` + `violations_of` **恒返回同一条固定违规**
  （迫使迭代但**不给方向**；常量不读裁决体 ⇒ 不暴露任何被判违规的内容）；
- **A3 现状**：`Budget()` 默认 + `routes.main.violations_for` 生产分流。

单变量阶梯与一处**推导**（为什么 A1 也用固定违规，勿改）
-------------------------------------------------------
- A1 → A2：自变量 = **轮数**（1 → 3），设计稿 §3.2 要求「两者都**无裁判方向信号**」
  ⇒ A1 MUST 与 A2 用同一个固定违规函数；若给 A1 接生产分流，这条阶梯会同时变动
  轮数与信号两个量 ⇒ 归因失效（`tests/test_bench_judge_gaming.py` 钉死）；
- A2 → A3：自变量 = **裁判信号**（预算逐字相同，只有 `violations_of` 不同）。

裁判与提示词（三臂**共用**，不是自变量）
--------------------------------------
- `judge` = 带 nlp 的 `analyze_a1_email`（生产同款）。**为什么不能退回内核默认裁判**：
  内核默认裁判不带 nlp ⇒ 语法族恒不生效 ⇒ 种子信号不被计数（v_0 == 0）⇒ A3 首轮即
  收敛、A2 vs A3 的自变量恒为零 —— 这正是设计稿 2026-10-15 修订倒逼的物理事实；
- `system_prompt = pick_system_prompt(_text_kind(analyze_a1_email(text)))`（生产同款
  选择规则；纯规则口径，不跑 spaCy）；
- `tools = POLISH_TOOL_ALLOWLIST`（生产白名单；dispatch 走内核默认同进程直调，
  与生产的 `call_tool` + 审计钩子在结果上等价，这里刻意不带钩子）。

`--dry-run`（零 Key、不出网）
----------------------------
stub chat 按**轮次**返回预构造回复（第 1 轮 `writing_check` 取证、第 2 轮 `analyze`
取证、第 3 轮收尾 ⇒ 轮数闸 1 vs 3 的差异被真实驱动），走完整链路：
chat → 工具分发（生产白名单）→ 证据追加 → 裁判（带 nlp）→ 生产分流 → 收敛/回退。
`tokens_used` / `elapsed_s` 取自循环自己的 `done` 事件（不另算一份账）。

退出码（照 `tools/bench_judge_fp.py` 惯例）
-----------------------------------------
`0` = 完成；`1` = 样本集无效（空集 / 缺 signal / 缺 probe / 注入字段破损 / id 重复）；
`2` = 环境不可用（依赖链 import 失败 / 德语模型不可用 / 真跑未接线 —— 属 Task 5/6）。

可复跑：同输入同输出（无随机；`elapsed_s` 是墙钟观测值，不参与判定）。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import enum
import importlib
import io
import json
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Sequence

# 允许从任意 CWD 直接 `python tools/bench_judge_gaming.py` 运行（同 tools/ 其余脚本约定）。
# 注意：这里**只**注入路径、不 import 仓库模块 —— 仓库 import 全部延迟到函数内
# （import 期零重依赖、零副作用；也让「环境不可用 ⇒ 退出码 2」有单一归口）。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if TYPE_CHECKING:  # 仅类型检查用：运行期延迟 import（见上）
    from delector.data.a1_seed_errors import SeedCase
    from delector.services.polish_loop import Budget as LoopBudget

# --------------------------------------------------------------------------- #
# 常量与类型
# --------------------------------------------------------------------------- #

#: `--dry-run` 的「模型」名（stub chat 的 `model_name` 属性；真跑时由真 chat 包装器
#: 提供生效模型名 —— `RunRecord.model` 只记名字，绝不记任何凭据）。
DRY_RUN_MODEL = "dry-run-stub"

#: `--dry-run` 前两轮取证用的工具名（必须在 `POLISH_TOOL_ALLOWLIST` 内，否则会被拒绝）。
DRY_RUN_TOOL_SEQUENCE: tuple[str, ...] = ("writing_check", "analyze")


class Arm(enum.Enum):
    """三臂（严格对应设计稿 §4 表格的行序；值进 JSON，属稳定契约）。"""

    A1_BASELINE = "a1_baseline"
    A2_NO_SIGNAL = "a2_no_signal"
    A3_CURRENT = "a3_current"


#: chat 注入缝的形状（与 `polish_loop.run_polish_loop` 的 chat 参数同形）。
ChatFn = Callable[..., Awaitable[dict[str, Any]]]

#: violations_of 注入缝的形状（单参：裁决体 ⇒ 被计数违规清单）。
ViolationsOf = Callable[[dict[str, Any]], list[dict[str, Any]]]

#: A2 的「无方向」信号：**恒同一条固定违规**。约束（MUST，有测试逐条钉住）：
#: - 与裁决体/文本无关（不读 verdict ⇒ 不可能暴露任何被判违规的内容）；
#: - A1 与 A2 共用（保证 A1→A2 的自变量只有轮数）；
#: - 内容是中性占位（不是生产规则名、不含任何语料文本）⇒ 模型即使感知也拿不到方向。
A2_FIXED_VIOLATION: dict[str, Any] = {
    "rule": "fixed_no_signal",
    "level": "error",
    "message": "固定违规（A2 无方向信号：与文本无关、恒同一条）",
}


@dataclass(frozen=True, slots=True)
class ArmConfig:
    """单臂配置（`build_arm` 的产物）：预算 + 违规抽取**工厂** + 人读标签。

    `violations_of_factory` 是工厂而不是函数本体：每篇每臂取一份「新鲜」可调用对象，
    把 A2 的常量、A3 的生产适配器、以及未来可能带状态的臂统一成同一形状（对齐
    `run_polish_loop` 的注入缝语义）。
    """

    arm: Arm
    arm_label: str
    budget: LoopBudget
    violations_of_factory: Callable[[], ViolationsOf]


@dataclass(frozen=True, slots=True)
class RunRecord:
    """一次（篇 × 臂）运行的记录（设计稿 §3.3 的记账面；Task 3 的输入）。

    - `final_text` / `rounds` / `reason` / `converged` 直接来自 `LoopResult`（循环自己的结论）；
    - `tokens_used` / `elapsed_s` 取自循环的 `done` 进度事件（**循环自己的记账**；
      harness 不另算一份，两处数字不一致时实验记账立刻失真）；
    - `model` 取 chat 可调用对象的 `model_name` 属性（stub ⇒ `DRY_RUN_MODEL`；真跑由真
      chat 包装器提供；缺席 ⇒ 空串，宁缺勿猜）。
    """

    arm: Arm
    case_id: str
    final_text: str
    rounds: int
    reason: str | None
    converged: bool
    tokens_used: int
    elapsed_s: float
    model: str


# --------------------------------------------------------------------------- #
# 三臂构造与注入缝实现
# --------------------------------------------------------------------------- #


def _fixed_no_signal_violations(_verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """A2（及 A1）的 `violations_of`：**不读裁决体**，恒返回同一条固定违规。

    - 恒一条 ⇒ v 永不归零 ⇒ 循环拿不到「修好了」的正反馈（无方向）；
    - 与裁决体无关 ⇒ 不可能暴露任何被判违规的内容（模型即使看见也拿不到方向；
      本实现的循环**根本不回灌**裁判违规 —— `messages.append` 没有该站点，这是双保险）。
    返回**新列表 + 新 dict**：防下游原地改写常量。
    """
    return [dict(A2_FIXED_VIOLATION)]


def _production_violations_of(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """A3 的 `violations_of`：生产分流（**逐字复用** `routes.main` 自己的单参适配器）。

    为什么复用生产实现而不是在 harness 里复刻：A3 的立论就是「现状」，复刻即引入漂移面
    （生产改了分流口径、实验仍按旧口径计数的静默失真）。
    """
    from delector.routes import main as routes_main

    return routes_main._polish_violations_of(verdict)


def build_arm(arm: Arm) -> ArmConfig:
    """构造三臂配置（**MUST 与设计稿 §4 表格逐条一致**）。

    - A1：`Budget(max_turns=1)` —— 对照基线（一次性润色等价物）；
    - A2：`Budget(max_turns=3)` + 恒定固定违规 —— 隔离「多轮」效应；
    - A3：`Budget()` 默认 + 生产分流 —— 被考核对象。

    A1 的 `violations_of` 也取固定违规的理由见模块头「单变量阶梯」：A1 只有 1 轮，
    固定违规在该臂里只影响「收尾候选是否被接受」（v 恒 1 ⇒ 不降即停），不产生任何方向。
    """
    from delector.services.polish_loop import Budget

    if arm is Arm.A1_BASELINE:
        return ArmConfig(
            arm=arm,
            arm_label="A1 基线（1 轮，无裁判方向信号）",
            budget=Budget(max_turns=1),
            violations_of_factory=lambda: _fixed_no_signal_violations,
        )
    if arm is Arm.A2_NO_SIGNAL:
        return ArmConfig(
            arm=arm,
            arm_label="A2 迭代无信号（≤3 轮，恒定固定违规）",
            budget=Budget(max_turns=3),
            violations_of_factory=lambda: _fixed_no_signal_violations,
        )
    if arm is Arm.A3_CURRENT:
        return ArmConfig(
            arm=arm,
            arm_label="A3 现状（≤3 轮，生产分流）",
            budget=Budget(),
            violations_of_factory=lambda: _production_violations_of,
        )
    raise ValueError(f"未知臂：{arm!r}")


# --------------------------------------------------------------------------- #
# 判官装配（生产同款；三臂共用）
# --------------------------------------------------------------------------- #

# spaCy 惰性加载的进程内缓存（import 期不加载、不联网；加载失败不写缓存）。
_NLP: Any = None

#: 「模型不可用」的统一人话原因（`_load_nlp` 抛出与 `probe_environment` 返回共用一份）。
_MODEL_UNAVAILABLE_REASON = (
    "德语模型不可用：de_core_news_md / de_core_news_sm 均无法本地加载"
    "（本脚本绝不自动下载；请先安装 de_core_news_sm）"
)


def _load_nlp() -> Any:
    """惰性加载德语模型（缓存；**绝不**触发自动下载 —— 与 `processor.try_load_nlp_no_download` 同纪律）。"""
    global _NLP
    if _NLP is not None:
        return _NLP
    from delector.nlp_engine import processor

    model = processor.try_load_nlp_no_download()
    if model is None:
        raise RuntimeError(_MODEL_UNAVAILABLE_REASON)
    _NLP = model
    return _NLP


def _make_production_judge(nlp: Any) -> Callable[[str, list[str] | None], dict[str, Any]]:
    """装配**生产同款**裁判（带 nlp 的 `analyze_a1_email`；与 `routes.main._make_judge(None, nlp)` 等价）。"""
    from delector.services.writing import analyze_a1_email

    def _judge(text: str, leitpunkte: list[str] | None = None) -> dict[str, Any]:
        return analyze_a1_email(text, leitpunkte, nlp)

    return _judge


# --------------------------------------------------------------------------- #
# 运行（三臂接线）
# --------------------------------------------------------------------------- #


def run_arm(case: SeedCase, arm: Arm, *, chat: ChatFn) -> RunRecord:
    """跑一篇种子 × 一个臂，返回 `RunRecord`（`chat` 由调用方注入 ⇒ 零 Key 可达）。

    三臂接线**完全共用**（见模块头），自变量只有 `build_arm` 的 budget / violations_of：
    `tools` 走生产白名单、`judge` 走带 nlp 的生产同款裁判、`system_prompt` 走生产同款
    选择规则；`on_progress` 只用来接住循环的 `done` 记账（tokens / elapsed）。
    """
    from delector.routes.main import _text_kind, pick_system_prompt
    from delector.services.polish_loop import run_polish_loop
    from delector.services.polish_tools import POLISH_TOOL_ALLOWLIST
    from delector.services.writing import analyze_a1_email

    config = build_arm(arm)
    judge = _make_production_judge(_load_nlp())
    kind = _text_kind(analyze_a1_email(case.text))
    events: list[dict[str, Any]] = []

    result = asyncio.run(
        run_polish_loop(
            text=case.text,
            tools=POLISH_TOOL_ALLOWLIST,
            budget=config.budget,
            chat=chat,
            judge=judge,
            violations_of=config.violations_of_factory(),
            system_prompt=pick_system_prompt(kind),
            on_progress=events.append,
        )
    )

    done = [event for event in events if event.get("event") == "done"]
    if not done:
        # 循环出口契约被破坏（done 事件缺席）⇒ 大声失败，不许静默记 0 token。
        raise RuntimeError("run_polish_loop 未发出 done 事件：循环记账缺失，拒绝伪造 RunRecord")
    return RunRecord(
        arm=arm,
        case_id=case.id,
        final_text=result.text,
        rounds=result.rounds,
        reason=result.reason,
        converged=result.converged,
        tokens_used=int(done[-1].get("tokens_used", 0)),
        elapsed_s=float(done[-1].get("elapsed", 0.0)),
        model=str(getattr(chat, "model_name", "")),
    )


def run_dry_run(cases: Sequence[SeedCase]) -> list[RunRecord]:
    """按「逐篇轮转」次序跑完全部用例 × 三臂（设计稿 §3.2 的交错执行；输出顺序确定）。"""
    records: list[RunRecord] = []
    for case in cases:
        for arm in Arm:
            records.append(run_arm(case, arm, chat=build_dry_run_chat(case)))
    return records


def record_to_dict(record: RunRecord) -> dict[str, Any]:
    """`RunRecord` ⇒ JSON 友好 dict（`arm` 落为它的稳定字符串值）。"""
    return {
        "arm": record.arm.value,
        "case_id": record.case_id,
        "final_text": record.final_text,
        "rounds": record.rounds,
        "reason": record.reason,
        "converged": record.converged,
        "tokens_used": record.tokens_used,
        "elapsed_s": record.elapsed_s,
        "model": record.model,
    }


# --------------------------------------------------------------------------- #
# --dry-run 桩 chat（按轮次的确定性脚本）
# --------------------------------------------------------------------------- #


class DryRunChat:
    """确定性 stub chat：`--dry-run` 零 Key 全链路的驱动源，按**轮次**返回预构造回复。

    脚本（与 max_turns 阶梯配合，让三臂的行为差异真实发生）：
    - 第 1 轮：`writing_check` 取证（payload.text = 种子原文）；
    - 第 2 轮：`analyze` 取证（同一原文；覆盖第二个白名单工具）；
    - 第 3 轮及以后：收尾候选 = `case.clean_text`（「完美模型」的确定性替身）。

    与真 chat 的差异（如实登记）：不读 messages、不做任何判断 —— 它测的是**管线**，
    不是模型行为（真模型行为属 Task 5/6 的 HITL 真跑）。`model_name` 属性是
    `RunRecord.model` 的取值来源（真跑的真 chat 包装器同形）。
    """

    model_name = DRY_RUN_MODEL

    def __init__(self, case: SeedCase) -> None:
        self._case = case
        self.calls = 0

    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]] | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        index = self.calls
        self.calls += 1
        if index < len(DRY_RUN_TOOL_SEQUENCE):
            return {"tool_call": {"name": DRY_RUN_TOOL_SEQUENCE[index], "payload": {"text": self._case.text}}}
        return {
            "corrected_text": self._case.clean_text,
            "notes_zh": ["dry-run 桩：预构造收尾回复（= 底本 clean_text）"],
        }


def build_dry_run_chat(case: SeedCase) -> DryRunChat:
    """构造一局的 dry-run stub chat（**每局一枚新实例**：脚本计数器必须逐局复位）。"""
    return DryRunChat(case)


# --------------------------------------------------------------------------- #
# 样本集校验（退出码 1 的归口）与环境探测（退出码 2 的归口）
# --------------------------------------------------------------------------- #

#: dry-run 全链路要用的仓库模块（延迟 import 的单一入口；import 期诊断行由调用方改道 stderr）。
_CHAIN_MODULES: tuple[str, ...] = (
    "delector.data.a1_seed_errors",
    "delector.nlp_engine.processor",
    "delector.routes.main",
    "delector.services.polish_loop",
    "delector.services.polish_tools",
    "delector.services.writing",
)


def _import_chain() -> None:
    """预热依赖链（任何一环装不上 ⇒ 抛异常 ⇒ 调用方映射为「环境不可用」）。"""
    for name in _CHAIN_MODULES:
        importlib.import_module(name)


def load_seed_cases() -> list[SeedCase]:
    """装载冻结种子集（Task 1 的 `SEED_CASES`；**逐字照搬**，不做任何修补）。"""
    from delector.data.a1_seed_errors import SEED_CASES

    return list(SEED_CASES)


def validate_seed_cases(cases: Sequence[SeedCase]) -> list[str]:
    """校验种子集在**本 harness 口径**下是否有效；返回问题列表（空 = 有效）。

    校验项（每一项都直接威胁实验可识别性，不是形式主义）：
    1. 样本集非空、每篇 id/text/clean_text 非空、id 不重复；
    2. `text != clean_text`（否则该篇没有任何注入，探针恒「已回收」）；
    3. 每篇**恰好 1 条** `kind == "signal"`：0 ⇒ v_0 == 0 ⇒ A3 首轮即收敛、实验对
       裁判信号不可识别（设计稿 2026-10-15 修订）；>1 ⇒ 计数口径漂移；
    4. 每篇至少 1 条 `kind == "probe"`（判决量分子，Task 3 起用）；
    5. 每条注入 `wrong`/`right` 非空、`expected_count >= 1`。
    """
    errors: list[str] = []
    if not cases:
        errors.append("样本集为空：SEED_CASES 没有任何用例")
        return errors

    seen_ids: set[str] = set()
    for case in cases:
        cid = case.id or "<无 id>"
        if not case.id.strip():
            errors.append(f"{cid}: id 为空")
        elif case.id in seen_ids:
            errors.append(f"{cid}: 重复的 case id")
        seen_ids.add(case.id)
        if not case.text.strip():
            errors.append(f"{cid}: text 为空")
        if not case.clean_text.strip():
            errors.append(f"{cid}: clean_text 为空")
        if case.text == case.clean_text:
            errors.append(f"{cid}: text 与 clean_text 相同（没有注入任何错误）")

        signals = [injection for injection in case.injections if injection.kind == "signal"]
        probes = [injection for injection in case.injections if injection.kind == "probe"]
        if len(signals) != 1:
            errors.append(
                f"{cid}: signal 注入应恰好 1 条（实际 {len(signals)}；0 ⇒ A3 首轮即收敛，实验对裁判信号不可识别）"
            )
        if not probes:
            errors.append(f"{cid}: probe 注入为 0（判决量分子缺失）")
        for injection in case.injections:
            if not injection.wrong.strip() or not injection.right.strip():
                errors.append(f"{cid}: 注入 {injection.error_class!r} 的 wrong/right 为空")
            if injection.expected_count < 1:
                errors.append(f"{cid}: 注入 {injection.error_class!r} 的 expected_count < 1")
    return errors


def probe_environment(loader: Callable[[], Any] | None = None) -> str | None:
    """环境探测（「退出码 2 = 环境不可用」的单一归口）：可用 ⇒ None，否则返回原因文本。

    `loader` 仅供测试注入（默认 `_load_nlp`）。两类故障都归这里：依赖链 import 失败
    （delector 自身 / spaCy 缺失）与德语模型不可用（**绝不**自动下载，与
    `processor.try_load_nlp_no_download` 同纪律）。
    """
    try:
        _import_chain()
    except Exception as exc:  # 宽捕是刻意的：任何一环装不上都是「环境不可用」，不是崩溃
        return f"依赖链 import 失败（{type(exc).__name__}: {exc}）"
    load = _load_nlp if loader is None else loader
    try:
        model = load()
    except (RuntimeError, ImportError) as exc:
        return str(exc)
    if model is None:
        # loader 以「返回 None」表达不可用（processor.try_load_nlp_no_download 的形态）
        # ⇒ 同样归「环境不可用」，不能静默放行。
        return _MODEL_UNAVAILABLE_REASON
    return None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _print_text_report(records: Sequence[RunRecord]) -> None:
    """文本模式：逐条原始记录（只报比例无法复核，故全量打印）+ 每臂汇聚行。"""
    print("=== bench_judge_gaming（§4.3 第 8 条对照实验 · 三臂 harness · --dry-run 全链路）===")
    print(f"records={len(records)}（逐篇三臂交错；stub chat 按轮次预构造；零 Key、不出网）")
    for record in records:
        print(
            f"[{record.case_id}] {record.arm.value}: rounds={record.rounds} reason={record.reason} "
            f"converged={record.converged} tokens={record.tokens_used} elapsed={record.elapsed_s:.3f}s "
            f"model={record.model}"
        )
    print()
    for arm in Arm:
        subset = [record for record in records if record.arm is arm]
        converged = sum(1 for record in subset if record.converged)
        print(f"[{arm.value}] runs={len(subset)} converged={converged}")
    print()
    print("退出码：0=完成；1=样本集无效（空集/缺 signal/缺 probe/注入破损）；")
    print("        2=环境不可用（依赖链 import 失败 / 德语模型不可用 / 真跑未接线）。")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。退出码：0=完成；1=样本集无效；2=环境不可用。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：德语字符需 UTF-8
        except Exception:  # 已关闭/不可重配置的流（如 pytest capture）⇒ 保持原状
            pass

    parser = argparse.ArgumentParser(
        description="§4.3 第 8 条对照实验的三臂 harness（Task 2 骨架：--dry-run 零 Key 全链路）。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="用确定性 stub chat 驱动 run_polish_loop 全链路（零 Key、不出网）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 输出 RunRecord 列表（stdout；逐篇三臂明细含全文）",
    )
    args = parser.parse_args(argv)

    if not args.dry_run:
        print(
            "[环境不可用] 真跑模式未接线：本骨架（Task 2）只提供 --dry-run；真跑属 Task 5/6"
            "（HITL，届时才接应用自身的凭据载入与 llm_client.chat）。",
            file=sys.stderr,
        )
        return 2

    # 依赖链 / 模型加载期的库级诊断行（processor 的 "[DeLector] NLP 引擎…"）一律改道 stderr：
    # `--json` 的 stdout 必须是**纯 JSON**。
    with contextlib.redirect_stdout(sys.stderr):
        try:
            cases = load_seed_cases()
        except Exception as exc:  # 种子集模块装不上 = 环境问题，不是样本集内容问题
            print(f"[环境不可用] 种子集模块装载失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

        errors = validate_seed_cases(cases)
        if errors:
            print(f"[样本集无效] 共 {len(errors)} 个问题（退出码 1）：", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
            return 1

        env_error = probe_environment()
        if env_error is not None:
            print(f"[环境不可用] {env_error}", file=sys.stderr)
            return 2

        records = run_dry_run(cases)

    if args.json:
        print(json.dumps([record_to_dict(record) for record in records], ensure_ascii=False, indent=2))
    else:
        _print_text_report(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
