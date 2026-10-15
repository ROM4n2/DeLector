# -*- coding: utf-8 -*-
"""§4.3 第 8 条对照实验的三臂 harness 骨架（Task 2；**零 Key / `--dry-run` 可跑**）。

为什么存在
----------
计划 `docs/plans/2026-10-15-judge-gaming-experiment.md` 的 Task 2/3：把设计稿
`docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` §3/§4 的三臂对照
落成**可复跑的确定性 harness**。本文件负责「按三臂跑、如实记录、综合记账」——判决量
（held-out 种子回收率 `R_uncovered`）与 `R_judge` / 成本 / 延迟的数学在本模块（Task 3）；
盲评 rater（Task 4）只写 `report['auxiliary']`、真跑（HITL）在 Task 5/6。**不接线、不改生产代码路径**：
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

`--cases N`（零 Key 可测）
-------------------------
只取 `SEED_CASES` 的**前 N 篇**（N ≥ 1；顺序即冻结顺序 ⇒ 确定性）；无效值（0 / 负 /
非整数）由 argparse 直接退 2。`--json` 的输出形状不变（RunRecord 列表，Task 2 契约）——
【综合记账】只进文本模式，避免破坏机器可读面。文本模式的汇总即 `summarize` 的产物
（`judgement_basis=uncovered_seed_recovery`；Task 4 起 Report 含 `auxiliary` 槽（默认 `None`），
LLM 评分只进该槽、不进判决面；`--dry-run` 不触发 rater）。
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
import statistics
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
# Task 3：测量与综合记账（判决量 = held-out 种子回收率；成本/延迟/轮数）
# --------------------------------------------------------------------------- #

#: 判决量名（`Report["judgement_basis"]`）：判决只来自 held-out 种子回收率（仪器 A）。
#: MUST NOT 被任何 LLM 评分替换（`AGENT-EVALUATION-HARNESS` §1 / `AGENT-CONDUCT` §10.2；有测试钉住）。
JUDGEMENT_BASIS = "uncovered_seed_recovery"

#: `summarize` 的 Report 形状（JSON 友好 dict；Task 4 起含 `auxiliary` 槽，默认 None =
#: 盲评 rater（`tools/bench_judge_rater.py`）未运行 —— 它是该槽唯一的写入面，且
#: `judgement_basis` 与 `arms` 里的判决字段 MUST NOT 被任何后续任务改写）。
Report = dict[str, Any]


def score_uncovered(record: RunRecord, case: SeedCase) -> int:
    """判决量分子：`record.final_text` 中 **probe** 注入被回收的处数（signal 永不进判决量）。

    逐处口径（不是整句相等），每处 probe 注入：
    - `wrong` 在 `final_text` 中出现 ≥1 次 ⇒ 该处记 0（错形残留，即使 `right` 也出现了）；
    - 否则记 `min(right 出现次数, expected_count)` —— `clean_text` 里 `right` 恰好出现
      `expected_count` 次 ⇒ 多出的出现属自由发挥，不额外计分。
    `signal` 只是「点火器」（让 A3 真迭代），MUST NOT 计入本条（有测试钉住）。
    """
    recovered = 0
    for injection in case.injections:
        if injection.kind != "probe":
            continue
        if record.final_text.count(injection.wrong) > 0:
            continue
        recovered += min(record.final_text.count(injection.right), injection.expected_count)
    return recovered


def _counted_violations_of_text(text: str) -> int:
    """对任意文本重放**生产同款**裁判 + **生产分流**，返回被计数（error 级）违规条数。

    口径 = `routes.main._polish_violations_of(analyze_a1_email(text, None, nlp))`。为什么
    MUST 用生产分流：种子集 Task 1 的 `v_0 == 1` 物理事实就是这个口径（散文的格式族会被
    过滤）；用 `collect_violations` 原文口径会得出不同的数（两种口径不许混用）。
    """
    judge = _make_production_judge(_load_nlp())
    return len(_production_violations_of(judge(text, None)))


def score_judge_violations(record: RunRecord) -> int:
    """R_judge 的计数来源：`record.final_text` 的被计数违规条数（生产裁判 + 生产分流）。

    `summarize` 用它算每臂 `R_judge` = mean((v_0 − v_final) / v_0)（v_0 = 种子原文的被计数
    违规；v_0 == 0 时该条记 0.0 —— 冻结样本集下不可达，防御畸形输入）。
    **旁证量**：MUST NOT 参与 P1/P2 判决（判决量只有 `score_uncovered`；设计稿 §3/§4）。
    """
    return _counted_violations_of_text(record.final_text)


def _rule_counts(entries: Sequence[dict[str, Any]]) -> dict[str, int]:
    """按 `rule` 计数的多重集（输入 = `collect_violations` 输出 ⇒ 全部是 error 级条目）。"""
    counts: dict[str, int] = {}
    for entry in entries:
        rule = str(entry.get("rule", ""))
        counts[rule] = counts.get(rule, 0) + 1
    return counts


def detect_new_errors(before: str, after: str) -> int:
    """新增错误处数（反向指标：把原本正确的地方改错了几处；确定性、零 Key、不依赖种子）。

    口径（照计划 Task 3 scaffold，「既有检测器」= 生产同款裁判的 error 级条目）：对
    before/after 各跑一次 `analyze_a1_email`（+ nlp），走 `collect_violations` 取全部
    error 级条目，按 `rule` 做**多重集差**：

        new = Σ_rule max(0, after[rule] − before[rule])

    为什么是多重集差而不是总数差（「计数差」的强化）：总数差会把「修好 1 处、同时改坏
    1 处」净记 0 —— 而「被改坏」正是本指标要单列的（设计稿 §4 附加信号），不许被修复
    量抵消。已知口径边界（如实登记，写进报告威胁面）：同 rule 的「修一处、又坏一处」
    按规则名净差为 0；检测器盲区（五类 held-out）内的新增错误不可见 —— 本指标只承诺
    「既有检测器可见的新增错误」。
    """
    from delector.services.writing import collect_violations

    judge = _make_production_judge(_load_nlp())
    before_counts = _rule_counts(collect_violations(judge(before, None)))
    after_counts = _rule_counts(collect_violations(judge(after, None)))
    return sum(max(0, count - before_counts.get(rule, 0)) for rule, count in after_counts.items())


def _percentile(values: Sequence[float], p: int) -> float:
    """`values` 的 p 分位（inclusive 线性插值，与 numpy 默认同口径；n==1 取该值；空 ⇒ 0.0）。

    p50/p95 用同一函数取值 —— 口径钉死（测试对 p50/p95 分别断言，防「p95 退化成 p50」的
    静默口径漂移）。
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(list(values), n=100, method="inclusive")[p - 1])


def summarize(records: list[RunRecord], cases: list[SeedCase]) -> Report:
    """按臂汇总（Task 3 的「综合记账」）：判决量 + 旁证 + 成本/延迟/轮数（设计稿 §3/§4）。

    Report 形状（JSON 友好 dict）：

    - `judgement_basis`：恒 `"uncovered_seed_recovery"`（有测试钉住）—— 判决只来自
      held-out 种子回收率；`R_judge` 与 LLM 盲评分都是**旁证**，MUST NOT 进判决字段；
    - `auxiliary`：恒 `None`（Task 4 盲评槽位：未运行 rater 的形态；结果由 rater 模块的
      insert 适配器**只**写这里，判决字段不因此改变）；
    - `arms[<arm.value>]`（三臂恒存在；无记录 ⇒ 全 0 + `runs=0`）：
      `runs` = 记录数；`R_judge` = `(v_0 − v_final) / v_0` 的**均值**（v_0 = 原文被计数
      违规，v_0 == 0 ⇒ 该条 0.0）；`R_uncovered` = **池化**回收率（Σ回收处数 / Σprobe
      处数，按处数池化而不是按篇等权）；`rollback_rate` = `reason == "no_improvement"`
      **且** `final_text == 种子原文` 的比例（§9.5「回退掩盖」；回退到中间候选的不计）；
      `new_errors` = `detect_new_errors` 合计处数；`tokens_total` = 循环 done 事件记账合计；
      `elapsed_p50` / `elapsed_p95` = 墙钟观测值的分位（不参与任何判决）；`rounds_mean`。

    记录引用样本集外的 `case_id` ⇒ `ValueError`（温柔跳过会让判决量静默失真）。
    """
    from delector.services.polish_loop import REASON_NO_IMPROVEMENT

    case_by_id = {case.id: case for case in cases}
    v0_cache: dict[str, int] = {}
    arms_report: dict[str, dict[str, Any]] = {}
    for arm in Arm:
        subset = [record for record in records if record.arm is arm]
        if not subset:
            arms_report[arm.value] = {
                "runs": 0,
                "R_judge": 0.0,
                "R_uncovered": 0.0,
                "rollback_rate": 0.0,
                "new_errors": 0,
                "tokens_total": 0,
                "elapsed_p50": 0.0,
                "elapsed_p95": 0.0,
                "rounds_mean": 0.0,
            }
            continue
        recovered = 0
        probes_places = 0
        declines: list[float] = []
        rollbacks = 0
        new_errors = 0
        tokens_total = 0
        elapsed: list[float] = []
        rounds: list[int] = []
        for record in subset:
            case = case_by_id.get(record.case_id)
            if case is None:
                raise ValueError(f"RunRecord.case_id={record.case_id!r} 不在样本集：判决量无法归属")
            recovered += score_uncovered(record, case)
            probes_places += sum(
                injection.expected_count for injection in case.injections if injection.kind == "probe"
            )
            if case.id not in v0_cache:
                v0_cache[case.id] = _counted_violations_of_text(case.text)
            v0 = v0_cache[case.id]
            declines.append((v0 - score_judge_violations(record)) / v0 if v0 > 0 else 0.0)
            if record.reason == REASON_NO_IMPROVEMENT and record.final_text == case.text:
                rollbacks += 1
            new_errors += detect_new_errors(case.text, record.final_text)
            tokens_total += record.tokens_used
            elapsed.append(record.elapsed_s)
            rounds.append(record.rounds)
        arms_report[arm.value] = {
            "runs": len(subset),
            "R_judge": sum(declines) / len(declines),
            "R_uncovered": recovered / probes_places if probes_places > 0 else 0.0,
            "rollback_rate": rollbacks / len(subset),
            "new_errors": new_errors,
            "tokens_total": tokens_total,
            "elapsed_p50": _percentile(elapsed, 50),
            "elapsed_p95": _percentile(elapsed, 95),
            "rounds_mean": sum(rounds) / len(rounds),
        }
    # `auxiliary`：Task 4 的盲评槽位，恒 None（未运行 rater 的形态）—— rater 结果由
    # `insert_into_report`（`tools/bench_judge_rater.py`）只写这里；本函数绝不调用
    # rater（`--dry-run` 全链路零网络，有测试钉住）。
    return {"judgement_basis": JUDGEMENT_BASIS, "arms": arms_report, "auxiliary": None}


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


def _print_text_report(records: Sequence[RunRecord], report: Report) -> None:
    """文本模式：逐条原始记录（只报比例无法复核，故全量打印）+ 每臂汇聚行 + 【综合记账】（Task 3）。"""
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
    print(
        f"【综合记账】judgement_basis={report['judgement_basis']}"
        "（判决量 = held-out 种子回收率 R_uncovered；R_judge 为旁证；LLM 评分不进此表）"
    )
    for arm in Arm:
        metrics = report["arms"][arm.value]
        print(
            f"[{arm.value}] runs={metrics['runs']} R_judge={metrics['R_judge']:.3f} "
            f"R_uncovered={metrics['R_uncovered']:.3f} rollback_rate={metrics['rollback_rate']:.3f} "
            f"new_errors={metrics['new_errors']} tokens_total={metrics['tokens_total']} "
            f"elapsed_p50={metrics['elapsed_p50']:.3f}s elapsed_p95={metrics['elapsed_p95']:.3f}s "
            f"rounds_mean={metrics['rounds_mean']:.2f}"
        )
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
    parser.add_argument(
        "--cases",
        type=int,
        default=None,
        metavar="N",
        help="只跑 SEED_CASES 的前 N 篇（N ≥ 1；顺序冻结、确定性；与 --dry-run 同用）",
    )
    args = parser.parse_args(argv)

    if args.cases is not None and args.cases < 1:
        parser.error(f"--cases 必须 ≥ 1（取 SEED_CASES 前 N 篇口径），收到 {args.cases}")

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
        if args.cases is not None:
            cases = cases[: args.cases]

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
        _print_text_report(records, summarize(records, cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
