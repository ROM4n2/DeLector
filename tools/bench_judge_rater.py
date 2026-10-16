# -*- coding: utf-8 -*-
"""§4.3 第 8 条对照实验的辅助仪器：盲评 rater（**不进判决**；Task 4）。

为什么存在
----------
设计稿 `docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` §3「仪器 B：盲评
质量分」：LLM-as-rater 对 (before, after) 文本对打 1–5 的「语法正确性」与「地道度」两项分。
合规前置（`AGENT-EVALUATION-HARNESS` §1 MUST / `AGENT-CONDUCT` §10.2）⇒ 判决量只有仪器 A
（held-out 种子回收率）；本模块的产物 MUST 只进 `report["auxiliary"]`，且逐字带
`role="auxiliary_signal_not_used_in_verdict"` 标记。`insert_into_report` 是该槽的唯一写入者；
「写进去后 `judgement_basis` 与 `arms` 逐字未变」有测试钉住。

盲评协议（MUST，逐条有测试）
---------------------------
- 呈现顺序由 `order_seed` 确定性决定：`"ba"` = 先 before 后 after；`"ab"` = 先 after 后
  before（两个分支都有测试；同一 seed 恒同序同请求）；
- 两个顺序共用**逐字一致**的 rubric（system 消息），只有两段文本的槽位互换；
- 发给模型的任何内容 MUST NOT 出现臂标签（`a1_baseline` / `a2_no_signal` / `a3_current`
  或 `A1`/`A2`/`A3` 之类暗示）或任何「哪份是润色后/原文」的归属提示 —— 两段文本一律以
  `Text 1` / `Text 2` 的盲槽呈现（有测试对请求全文逐词扫描）。

零 Key（MUST）
-------------
`chat` 一律由调用方注入（**签名里没有默认值**：本模块绝不提供真 chat、绝不读任何 Key
载入路径、绝不触网；真 chat 接线属 Task 5/6）。调用形制与 `polish_loop` 的 chat 调用逐字
同形（`messages` / `model` / `timeout` / `max_tokens` / `response_format`），Task 5/6 接
`llm_client.chat`（同一 key 加载路径）时天然兼容；`model=""` 是「注入 chat 时不读配置」的
既有约定（同 `run_polish_loop`；真接线由包装器自己取生效模型名）。本模块保持纯 stdlib：
不 import 仓库任何模块（import 期零依赖、零副作用；也让「零 Key 载入路径」在源码层可扫）。

一对文本一次调用（设计稿 §8 的「≈120 次轻量调用」是 2 次/对 的保守上界；本实现 1 次/对
返回四项分 = 两段 × 两维 —— 更省，评分口径不变）。

可执行入口（⑥）
---------------
`python tools/bench_judge_rater.py --pairs <json>` = **结构冒烟** CLI：零 Key、零网络，用确定性
stub chat 跑通「读对 → 盲评请求 → 去盲 → 序列化」全管线（真模型接线属 Task 5/6，不在本任务）。
它补的是交付物清单里"rater 有可执行入口"这一项 —— 但**绝不**冒充真盲评（输出头与 `--help`
均标注 stub）。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
from typing import Any, Callable, Coroutine

#: Report 的形状与 `tools/bench_judge_gaming.py::summarize` 的产物同形（本模块不 import
#: 该脚本：tools/ 不是 package，避免路径耦合；两侧键名由测试交叉钉住）。
Report = dict[str, Any]

#: chat 注入缝的形状（与 `run_polish_loop` 的 chat 参数同形：关键词调用；
#: 承 `asyncio.run` 的接受面 ⇒ 精确到 `Coroutine`，运行期对一切 awaitable 兼容）。
ChatFn = Callable[..., Coroutine[Any, Any, dict[str, Any]]]

#: 盲评结果的角色标记（**逐字**进 `report["auxiliary"]["role"]`；有测试钉住）：
#: 辅助信号、未参与判决 —— 报告消费方必须能一眼看出它不进 P1/P2 判定。
AUXILIARY_ROLE = "auxiliary_signal_not_used_in_verdict"

#: 呈现顺序取值：`"ba"` = 先 before 后 after；`"ab"` = 先 after 后 before。
ORDER_BA = "ba"
ORDER_AB = "ab"

#: 单次盲评调用的超时（s）——与生产 ai-polish 端现值 30.0s 同值（不引入新预算口径）。
RATER_TIMEOUT_S = 30.0

#: 单次盲评调用的 completion 上限（回复是短 JSON；512 留足）。
RATER_MAX_TOKENS = 512

#: 结构化输出开关（与 `delector.services.llm_client.JSON_OBJECT` 逐字同值；本模块刻意
#: 不 import 仓库模块 —— 见模块头「零 Key」）。
JSON_OBJECT: dict[str, str] = {"type": "json_object"}

#: 盲评 rubric（两个呈现顺序**共用同一份**，逐字一致；有测试对两序抓包比对）。
#: MUST NOT 出现臂标签 /「润色后」「原文」等归属暗示（有测试扫描请求全文）。
RATER_SYSTEM_PROMPT = (
    "你是德语写作质量的盲评员。你会看到两段独立的德语文本（Text 1 与 Text 2），"
    "请只依据文本本身评分，不要推测两段文本的关系或来源。\n"
    "对每段文本各打两项 1–5 的整数分：\n"
    "- correctness：语法正确性（1 = 多处明显语法错误，5 = 无明显语法错误）；\n"
    "- idiomatic：地道度（1 = 明显不自然，5 = 完全地道自然）。\n"
    "只回复一个 JSON 对象，不要输出任何其他文字，形状为：\n"
    '{"text1": {"correctness": <1-5 的整数>, "idiomatic": <1-5 的整数>}, '
    '"text2": {"correctness": <1-5 的整数>, "idiomatic": <1-5 的整数>}}'
)


@dataclasses.dataclass(frozen=True, slots=True)
class Rating:
    """一对 (before, after) 的盲评结果（**辅助信号**：只配进 `report["auxiliary"]`）。

    - 四项分是**去盲后**的口径（键名都带 before/after，消费方不需要自己解 order）；
    - `order` 记录盲评时的呈现顺序（`"ba"` / `"ab"`）：报告里可审计「当时谁在前」，
      MUST NOT 用于任何判决 —— 它进的也是 `auxiliary`，不是判决字段。
    """

    correctness_before: int
    correctness_after: int
    idiomatic_before: int
    idiomatic_after: int
    order: str


def _pair_messages(first: str, second: str) -> list[dict[str, Any]]:
    """构造盲评请求：system = rubric（两序逐字一致）；user = 两段文本的中性盲槽。

    槽位标签只用 `Text 1` / `Text 2`：任何臂标签或「哪份是润色后」的暗示 MUST NOT
    出现在这里（有测试对请求全文逐词扫描）。
    """
    return [
        {"role": "system", "content": RATER_SYSTEM_PROMPT},
        {"role": "user", "content": f"Text 1:\n{first}\n\nText 2:\n{second}"},
    ]


def _order_for(order_seed: int) -> str:
    """`order_seed` ⇒ 呈现顺序（确定性：偶数 ⇒ `ba`，奇数 ⇒ `ab`）。"""
    return ORDER_BA if order_seed % 2 == 0 else ORDER_AB


def _scores_of(reply: Any, slot: str) -> dict[str, int]:
    """取回复里一个槽（`text1`/`text2`）的两项分；形状不合法 ⇒ ValueError（不猜、不归零）。"""
    entry = reply.get(slot) if isinstance(reply, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"盲评回复缺少 {slot} 槽（或形状不合法）：{str(reply)[:200]}")
    scores: dict[str, int] = {}
    for item in ("correctness", "idiomatic"):
        value = entry.get(item)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
            raise ValueError(f"盲评 {slot}.{item} 必须是 1–5 的整数，收到 {value!r}")
        scores[item] = value
    return scores


def rate_pair(before: str, after: str, *, order_seed: int, chat: ChatFn) -> Rating:
    """盲评一对 (before, after) 文本，返回**去盲后**的 `Rating`（一对文本一次调用）。

    - 呈现顺序由 `order_seed` 决定（`_order_for`）；两个顺序的 rubric 逐字一致；
    - `chat` 由调用方注入（**无默认值**：本模块不触任何 Key 载入路径、不出网）；
    - 回复形状不合法 ⇒ ValueError（辅助信号宁缺勿假：畸形分不得静默变成 0 分混进报告）。
    """
    if not before.strip() or not after.strip():
        raise ValueError("rate_pair 拒绝空（或纯空白）文本：空文本的评分会污染辅助信号（宁缺勿假）")
    order = _order_for(order_seed)
    first, second = (before, after) if order == ORDER_BA else (after, before)
    reply = asyncio.run(
        chat(
            messages=_pair_messages(first, second),
            model="",
            timeout=RATER_TIMEOUT_S,
            max_tokens=RATER_MAX_TOKENS,
            response_format=JSON_OBJECT,
        )
    )
    first_scores = _scores_of(reply, "text1")
    second_scores = _scores_of(reply, "text2")
    before_scores, after_scores = (
        (first_scores, second_scores) if order == ORDER_BA else (second_scores, first_scores)
    )
    return Rating(
        correctness_before=before_scores["correctness"],
        correctness_after=after_scores["correctness"],
        idiomatic_before=before_scores["idiomatic"],
        idiomatic_after=after_scores["idiomatic"],
        order=order,
    )


def insert_into_report(report: Report, ratings: list[Rating]) -> Report:
    """把盲评结果**只**写进 `report["auxiliary"]`，返回新 Report（原 report 不被改动）。

    - `auxiliary = {"role": AUXILIARY_ROLE, "ratings": [...]}`（role 逐字钉住；ratings 为
      JSON 友好的 `dataclasses.asdict` 形态 —— 写进评级后的 Report 整体可序列化）；
    - `judgement_basis` 与 `arms` 的全部判决字段 MUST NOT 被本函数触碰（有测试逐字断言
      「写进去后判决面未变」）；本函数是 `report["auxiliary"]` 的唯一写入面。
    """
    merged: Report = dict(report)
    merged["auxiliary"] = {
        "role": AUXILIARY_ROLE,
        "ratings": [dataclasses.asdict(rating) for rating in ratings],
    }
    return merged


# --------------------------------------------------------------------------- #
# 可执行入口（⑥）：结构冒烟 CLI（零 Key、零网络；真模型由调用方注入，属 Task 5/6）
# --------------------------------------------------------------------------- #


def _load_pairs(path: str) -> list[dict[str, str]]:
    """读 (id, before, after) 文本对：JSON 数组，每项含 before/after（id 可选）。

    形状不合法 ⇒ ValueError（不猜、不补）：盲评的输入面宁可显式失败，也不能静默丢对。
    """
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"--pairs 文件必须是 JSON 数组：{path}")
    pairs: list[dict[str, str]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"--pairs[{index}] 必须是对象（含 before/after）")
        before = item.get("before")
        after = item.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            raise ValueError(f"--pairs[{index}] 的 before/after 必须是字符串")
        pairs.append({"id": str(item.get("id", index)), "before": before, "after": after})
    return pairs


class StubRatingChat:
    """结构冒烟用的**确定性** stub chat（零 Key、零网络）：回固定的合法评分形状。

    为什么它不"真评分"：本入口测的是**管线可执行**（读对 → 构造盲评请求 → 去盲映射 →
    序列化），**不是**模型质量；真模型评分必须由调用方注入 chat（Task 5/6 接
    `llm_client.chat`）。输出头与 `--help` 都如实标注「stub」——不冒充真盲评。
    """

    model_name = "rater-cli-stub"

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "text1": {"correctness": 3, "idiomatic": 3},
            "text2": {"correctness": 3, "idiomatic": 3},
        }


def main(argv: list[str] | None = None) -> int:
    """rater 可执行入口（⑥，**结构冒烟**）：对 `--pairs` 的文本对跑盲评管线并输出评级 JSON。

    零 Key、零网络（用确定性 stub chat）；真模型接线属 Task 5/6。退出码：`0` = 完成；
    `2` = 参数 / 输入文件不可用（与 harness 的 0/1/2 惯例一致）。
    """
    parser = argparse.ArgumentParser(
        description="盲评 rater 结构冒烟 CLI（零 Key、零网络；真模型由调用方注入，属 Task 5/6）。",
    )
    parser.add_argument(
        "--pairs",
        required=True,
        metavar="PATH",
        help="JSON 数组文件：每项含 before/after（id 可选）",
    )
    parser.add_argument(
        "--order-seed",
        type=int,
        default=0,
        metavar="N",
        help="盲评呈现顺序种子（偶数 ba / 奇数 ab；逐对 +1 轮换）",
    )
    args = parser.parse_args(argv)

    try:
        pairs = _load_pairs(args.pairs)
    except (OSError, ValueError) as exc:
        print(f"[rater] 输入不可用：{exc}", file=sys.stderr)
        return 2

    chat = StubRatingChat()
    ratings: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        rating = rate_pair(pair["before"], pair["after"], order_seed=args.order_seed + index, chat=chat)
        ratings.append({"id": pair["id"], **dataclasses.asdict(rating)})
    print(json.dumps({"role": AUXILIARY_ROLE, "ratings": ratings}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())