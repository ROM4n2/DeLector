# -*- coding: utf-8 -*-
"""§4.3 第 8 条对照实验的三臂 harness（Task 2 骨架 + Task-5a `--real` 真跑接线；`--dry-run` 零 Key 全链路）。

为什么存在
----------
计划 `docs/plans/2026-10-15-judge-gaming-experiment.md` 的 Task 2/3/5：把设计稿
`docs/specs/2026-10-15-judge-gaming-control-experiment-design.md` §3/§4 的三臂对照
落成**可复跑的确定性 harness**。本文件负责「按三臂跑、如实记录、综合记账」——判决量
（held-out 种子回收率 `R_uncovered`）与 `R_judge` / 成本 / 延迟的数学在本模块（Task 3）；
盲评 rater（Task 4）只写 `report['auxiliary']`；真跑 = Task-5a 接线的 `--real`（本文件），
运行由 HITL（编排者 / 用户）触发。**不改生产代码路径**：只经 `run_polish_loop` 的注入缝
复用生产链路（chat / tools / budget / judge / violations_of / system_prompt / on_progress），
不改内核语义。

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

`--real`（真跑，HITL；Task-5a 接线）
----------------------------------
真跑与 `--dry-run` **共用同一条链路**（`run_arm` × 三臂、同一次序），唯一差异 = 驱动源：

- 运行期先经 `delector.server.load_env()` 载入环境（**全文件唯一调用点、只住本分支** ——
  与生产同源，不在 harness 里复刻 .env 解析；`--dry-run` 绝不触它，有测试用「调用即炸」
  的 stub 钉住）；
- 真 chat = `RealChat`，与 `routes.main._PolishReplyRecorder`（ai-polish 生产构造）**逐参
  同形**：循环传入的 model 空串被忽略、以 `get_effective_api_model()` 生效模型名出网；
  timeout / max_tokens / response_format 原样透传（单次调用有界 = 循环的
  `min(30.0s, 剩余 deadline)`）；额外只加 `model_name` / `temperature` 读取面
  （`RunRecord.model` / `RunRecord.temperature`）；**temperature 显式钉定**（③，
  `EXPERIMENT_TEMPERATURE`，三臂共用）并 **opt-in** 请求 `usage` 透出（⑦）；
  对 429/5xx/传输层错做**有界重试**（②，≤2 次、指数退避 + jitter；chat 无副作用 ⇒ 幂等）；
- 真跑前先做**连通预检**（④）：发一次最小 chat（`parse_json=False`、`max_tokens=5`），
  失败即退 2（正式跑之前拦下"根本没通"的场景；预检本身用 stub 测，绝不真发请求）；
- 真跑前 stderr 打印**非泄值**事实：`key 存在=<bool>` 与生效模型名（**绝不打印 key 本体**；
  任何输出 / 异常 / 日志都不带 key —— 「key 存在」布尔由 key 判定面归约而来）；
- 失败语义（**绝不静默**）：无 Key / 运行期依赖不可用 / 连通预检失败 ⇒ 前置退 2（stderr 人话）；
  上游错误的处理分两档（②）：**可重试**（429/5xx/传输层）重试耗尽后把该单元标 `status="failed"`
  并**继续**下一篇（不再全跑中止 —— 一次瞬断不再让整轮实验白跑）；**不可重试**（如 401/402）
  仍原样冒泡 ⇒ 显式退 2（凭据/配置类错误继续跑也没意义）；
- 输出面与 `--dry-run` 一致：文本模式全量记录 + 【综合记账】；`--json` 仍为 RunRecord 列表
  （Task 4 起 15 键，见 `RunRecord`）。

零 Key 红线的现行形态：`--dry-run` 全链路仍零 Key、零网络（socket 闸 + `llm_client.chat`
闸 + 产物 tripwire）；`--real` 的 Key 接触面被三条钉子夹住 —— 唯一调用点（AST 计数）、
非泄值打印面、输出 / 异常零 key（假 key 全程 tripwire）。

退出码（照 `tools/bench_judge_fp.py` 惯例）
-----------------------------------------
`0` = 完成；`1` = 样本集无效（空集 / 缺 signal / 缺 probe / 注入字段破损 / id 重复）；
`2` = 环境不可用或真跑失败（依赖链 import 失败 / 德语模型不可用 / 无模式旗标或两旗标同给 /
无 Key / 连通预检失败 / 存在重试耗尽被标 `failed` 的单元）；
`3` = **成本硬闸触顶**（⑤；与 0/1/2 区分开的独立码；`--max-total-tokens` / `--max-est-cost`）。

可复跑：**修正旧陈述**。旧文档写「同输入同输出（无随机）」，这对 `--real` 是**假陈述**：
DeepSeek **无 `seed` 参数** ⇒ 采样有随机性、同输入不保证同输出。确定性只成立于 `--dry-run`
（stub 按轮次脚本）；`--real` 下 `elapsed_s` 是墙钟观测值、采样随机，均不参与判决。本实验把
`temperature` 显式钉定为**唯一可消除的随机源**（③），但**不**声称「同输入同输出」。

工程前置（Task 4 / B5 七件；本任务**不触发真跑**）
-------------------------------------------------
① **逐篇增量落盘 + `--resume`**：每（篇 × 臂）跑完即写一行 JSONL（`--save <path>`；含
   `case_id` / `arm` / 完整 `RunRecord`）并 flush+fsync —— 一次瞬断最多丢当前一篇的当前臂；
   `--resume` 重跑只补缺（已落盘单元跳过，幂等；否则一次瞬断即全损）。
② **有界重试**：429/5xx/传输层错 ≤ `MAX_RETRIES` 次、指数退避 + jitter（chat 无副作用 ⇒ 幂等）；
   超限把该单元标 `status="failed"` 并**继续**下一篇。
③ **`temperature` 显式钉定并记入 `RunRecord`**（`EXPERIMENT_TEMPERATURE`）；输出头记模型名 +
   「DeepSeek 无 `seed` ⇒ 同输入不同输出」的**事实声明**。
④ **`--real` 连通预检**：正式跑前发一次最小 chat，失败即退 2。
⑤ **成本硬闸**：`--max-total-tokens` / `--max-est-cost`；触顶即停并退**独立码 3**。
⑥ rater 补可执行入口住 `tools/bench_judge_rater.py`（结构冒烟 CLI；本文件零引用，见 tripwire）。
⑦ `llm_client.chat` **opt-in** `include_usage` ⇒ `RunRecord` 记**真** prompt/completion token，
   并**并列**保留 `ceil(len/3.0)` 估算作对照（估算系数 `3.0` 仍标 UNVERIFIED）。

Task-4b 附带指标（W4 裁决落地；**不进判决**）
-------------------------------------------
「回退前最后候选回收率」：A1/A2 的恒定固定违规迫使 `no_improvement` 收官 ⇒ final 恒回退原文
⇒ `R_uncovered`(final) ≡ 0 掩盖了迭代产出（设计稿 2026-10-16 修订段）。`run_arm` 用
`_ChatRecorder`（**完全透明**的 chat 包装器：原样返回 / 原样入参 / 异常原样冒泡）记录本局
最后一次 `corrected_text` ⇒ `RunRecord.last_candidate_text`；`summarize` 每臂增
`R_uncovered_last_candidate`（仅池化「有候选」的记录）/ `candidates_recorded`。二者 MUST NOT
进 P1/P2 判决（判决量仍 `R_uncovered`）—— 生产代码路径零变更（包装器只住 harness）。

`--cases N`（零 Key 可测；与 `--dry-run` / `--real` 同用）
---------------------------------------------------------
只取 `SEED_CASES` 的**前 N 篇**（N ≥ 1；顺序即冻结顺序 ⇒ 确定性；切片在装载后、校验前）；
无效值（0 / 负 / 非整数）由 argparse 直接退 2。`--json` 的输出形状不变（RunRecord 列表，Task 2 契约）——
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
import math
import os
import random
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

#: ③ 实验固定的 `temperature`：三臂共用、显式钉进 payload（`--real`）并逐字记入 `RunRecord`。
#: 为什么钉 0.0：DeepSeek **无 `seed`** ⇒ 无法保证同输入同输出；钉住 temperature 是**唯一**
#: 可消除的采样随机源。剩下的采样随机性必须在输出头如实声明（不冒充「可复跑同输出」）。
EXPERIMENT_TEMPERATURE: float = 0.0

#: ③ 输出头的**事实声明**（对旧文档「可复跑：同输入同输出（无随机）」那句假陈述的修正）。
NO_SEED_FACT_STATEMENT = (
    "事实声明：DeepSeek 无 `seed` 参数 ⇒ 同输入**不保证**同输出（采样有随机性）；"
    f"本实验已把 temperature 钉定为 {EXPERIMENT_TEMPERATURE}（唯一可消除的随机源），"
    "但**不**声称「同输入同输出」。"
)

#: ② 有界重试：最多 2 次重试（共 3 次尝试）。只对 429/5xx/传输层错（chat 无副作用 ⇒ 幂等）。
MAX_RETRIES = 2

#: ② 指数退避的基准秒数（第 n 次重试前睡 `base * 2**n + jitter`；测试可注入 sleep/置 0）。
RETRY_BASE_DELAY_S = 1.0

#: ④ 连通预检的最小 chat 超时（s）。单次有界（反挂死红线：任何网络调用 MUST 有超时）。
CONNECTIVITY_PRECHECK_TIMEOUT_S = 30.0

#: ⑤ 成本硬闸触顶的**独立退出码**（与 0/1/2 区分开；写进 `--help` 与文本输出的退出码说明）。
EXIT_COST_CAP = 3

#: ⑤ 估算成本口径（**UNVERIFIED 假设**）：对 (prompt + completion) token 用一个**混合**单价
#: 折算美元。为什么是"混合单价"而不是 prompt/completion 分开计价：本仓**无任何**价目表
#: （全仓 grep 零命中），此值是为让 `--max-est-cost` 成为一个**可设的硬闸**而立的**显式假设**，
#: 不是对 DeepSeek 真实计价的断言 —— 命名与注释都标 UNVERIFIED，`--max-total-tokens` 才是
#: 不依赖计价假设的**主闸**。
EST_COST_PER_1K_TOKENS_USD: float = 0.001


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
      chat 包装器提供；缺席 ⇒ 空串，宁缺勿猜）；
    - `last_candidate_text`（Task-4b，**有意契约演进**）：本局最后一次 `corrected_text`
      （`_ChatRecorder` 透明记录；`None` = 全程无候选）—— 附带指标的记录面，MUST NOT 进
      P1/P2 判决（判决量仍 `R_uncovered`）。
    - Task 4 增五键（②③⑦，**有意契约演进**）：
      `temperature` = 本局钉定的采样温度（③；`getattr(chat, "temperature", EXPERIMENT_TEMPERATURE)`）；
      `prompt_tokens` / `completion_tokens` = **真值**（⑦；usage 透出，缺失 ⇒ 0）；
      `estimated_completion_tokens` = `ceil(len/3.0)` 的**估算对照**（⑦；系数仍标 UNVERIFIED）；
      `status` = `"ok"` / `"failed"`（②：重试耗尽后标 failed 并继续；failed 记录 `final_text`
      为原文、`reason="failed"`）。
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
    last_candidate_text: str | None
    temperature: float
    prompt_tokens: int
    completion_tokens: int
    estimated_completion_tokens: int
    status: str


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
# Task-4b / ⑦：透明 chat 包装器（附带指标 + 真值/估算计量的记录面）
# --------------------------------------------------------------------------- #

#: ⑦ 估算系数的**同源口径**（与 `polish_loop.CHARS_PER_TOKEN_ESTIMATE = 3.0` 逐字同值；
#: 本模块不 import 生产模块以求 import 期零依赖，故此处复写并标 UNVERIFIED，有测试交叉钉住同值）。
_CHARS_PER_TOKEN_ESTIMATE = 3.0


def _estimate_tokens(text: str) -> int:
    """`ceil(len/3.0)` 估算（**UNVERIFIED 假设**；⑦ 的对照口径，与生产 `estimate_tokens` 同源）。"""
    return math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE)


def _dump(obj: Any) -> str:
    """确定性序列化（`sort_keys`；与 `polish_loop._dump` 同口径 ⇒ 估算可复现）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class _ChatRecorder:
    """**完全透明**的 chat 包装器：原样转发到 `inner`，额外记录候选文本与 token 计量。

    透明度契约（有测试逐条钉住）：
    - 返回值：原样返回 `inner` 的回复对象（同一性；不拷贝、不改写）；
    - 入参：messages / 其余 kwargs 一律原样透传（不修、不补、不删）；
    - 异常：原样冒泡（不吞、不换类、不包装）；
    - `model_name`：读时透传 `inner` 的同名属性（缺席 ⇒ 空串，与 `run_arm` 读取口径一致）。

    「最后候选」口径：reply 是 dict 且 `corrected_text` 是 **str 型**时记录（**后覆盖前**；
    空串照「含该键即记录」的口径也记录）；其余形状不改记录。初值 `None` = 全程无候选。

    ⑦ 计量口径（每次回复累加，**不改** reply 本身）：
    - `prompt_tokens` / `completion_tokens`：reply 带 `usage`（`llm_client.chat` 的
      opt-in `include_usage`）时取**真值**；缺失 ⇒ 该次记 0（真值缺席不用估算冒充）；
    - `estimated_completion_tokens`：对**每次**回复做 `ceil(len(dump(reply))/3.0)` 累加
      （**对照口径**，无论真值是否在场都算，便于并列比对系数）。

    为什么记录面住 harness 而不动生产循环：实验纪律「不改生产代码路径」。
    """

    def __init__(self, inner: ChatFn) -> None:
        self._inner = inner
        self.last_candidate_text: str | None = None
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.estimated_completion_tokens = 0

    @property
    def inner(self) -> ChatFn:
        """被包装的 chat（测试断言「包装器内层 == 注入 chat」的读取面）。"""
        return self._inner

    @property
    def model_name(self) -> str:
        """透传 inner 的 `model_name`（缺席 ⇒ 空串，与 `run_arm` 的读取口径一致）。"""
        return str(getattr(self._inner, "model_name", ""))

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        reply = await self._inner(**kwargs)
        if isinstance(reply, dict):
            candidate = reply.get("corrected_text")
            if isinstance(candidate, str):
                self.last_candidate_text = candidate
            self.estimated_completion_tokens += _estimate_tokens(_dump(reply))
            usage = reply.get("usage")
            if isinstance(usage, dict):
                self.prompt_tokens += _usage_int(usage, "prompt_tokens")
                self.completion_tokens += _usage_int(usage, "completion_tokens")
        return reply


def _usage_int(usage: dict[str, Any], key: str) -> int:
    """从 `usage` 取一个非负整数计量（缺失 / 畸形 ⇒ 0；真值缺席不猜）。"""
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0
    return int(value)


# --------------------------------------------------------------------------- #
# 运行（三臂接线）
# --------------------------------------------------------------------------- #


def run_arm(case: SeedCase, arm: Arm, *, chat: ChatFn, feedback: bool = False) -> RunRecord:
    """跑一篇种子 × 一个臂，返回 `RunRecord`（`chat` 由调用方注入 ⇒ 零 Key 可达）。

    三臂接线**完全共用**（见模块头），自变量只有 `build_arm` 的 budget / violations_of：
    `tools` 走生产白名单、`judge` 走带 nlp 的生产同款裁判、`system_prompt` 走生产同款
    选择规则；`on_progress` 只用来接住循环的 `done` 记账（tokens / elapsed）。
    `feedback`（Task 5）：默认 False（维持 ADR-0024 准入式基线）；True 时开启裁判结论回灌。

    Task-4b：注入的 `chat` 先过 `_ChatRecorder`（透明包装器）—— 循环拿到的永远是包装器，
    对外行为与未包装逐字一致（原样返回 / 原样入参 / 异常原样冒泡，有测试钉住）；本局最后
    一次 `corrected_text` 记入 `RunRecord.last_candidate_text`（附带指标，不进判决）。
    """
    from delector.routes.main import _text_kind, pick_system_prompt
    from delector.services.polish_loop import run_polish_loop
    from delector.services.polish_tools import POLISH_TOOL_ALLOWLIST
    from delector.services.writing import analyze_a1_email

    config = build_arm(arm)
    judge = _make_production_judge(_load_nlp())
    kind = _text_kind(analyze_a1_email(case.text))
    events: list[dict[str, Any]] = []
    recorder = _ChatRecorder(chat)

    result = asyncio.run(
        run_polish_loop(
            text=case.text,
            tools=POLISH_TOOL_ALLOWLIST,
            budget=config.budget,
            chat=recorder,
            judge=judge,
            violations_of=config.violations_of_factory(),
            system_prompt=pick_system_prompt(kind),
            feedback=feedback,
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
        last_candidate_text=recorder.last_candidate_text,
        # ③ 钉定的温度：真 chat 暴露 `temperature` 属性；缺席（stub）⇒ 用实验常量。
        temperature=float(getattr(chat, "temperature", EXPERIMENT_TEMPERATURE)),
        # ⑦ 真值（usage 透出；缺失 ⇒ 0）+ 估算对照（ceil(len/3.0)，**无论真值是否在场**）。
        prompt_tokens=recorder.prompt_tokens,
        completion_tokens=recorder.completion_tokens,
        estimated_completion_tokens=recorder.estimated_completion_tokens,
        status="ok",
    )


def record_to_dict(record: RunRecord) -> dict[str, Any]:
    """`RunRecord` ⇒ JSON 友好 dict（`arm` 落为它的稳定字符串值）。

    Task-4b + Task 4 **有意契约演进**（非回归）：第十键 `last_candidate_text`（附带指标的记录面；
    `null` = 全程无候选）+ Task 4 的五键（`temperature` / `prompt_tokens` / `completion_tokens` /
    `estimated_completion_tokens` / `status`）—— `--json` 的 records 列表同步为 **15 键**，消费方需知。
    这也是 JSONL 落盘（①）每行的形状。
    """
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
        "last_candidate_text": record.last_candidate_text,
        "temperature": record.temperature,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "estimated_completion_tokens": record.estimated_completion_tokens,
        "status": record.status,
    }


def _record_from_dict(data: dict[str, Any]) -> RunRecord:
    """`record_to_dict` 的逆（①：`--resume` 从 JSONL 读回既有记录）。缺键大声失败、不猜。"""
    return RunRecord(
        arm=Arm(data["arm"]),
        case_id=str(data["case_id"]),
        final_text=str(data["final_text"]),
        rounds=int(data["rounds"]),
        reason=data["reason"],
        converged=bool(data["converged"]),
        tokens_used=int(data["tokens_used"]),
        elapsed_s=float(data["elapsed_s"]),
        model=str(data["model"]),
        last_candidate_text=data["last_candidate_text"],
        temperature=float(data["temperature"]),
        prompt_tokens=int(data["prompt_tokens"]),
        completion_tokens=int(data["completion_tokens"]),
        estimated_completion_tokens=int(data["estimated_completion_tokens"]),
        status=str(data["status"]),
    )


# --------------------------------------------------------------------------- #
# ① 逐篇增量落盘（JSONL）+ ⑤ 成本硬闸 + ② 失败单元执行器
# --------------------------------------------------------------------------- #


class CostGate:
    """⑤ 成本硬闸：累计 (prompt + completion) token 与估算成本，越限即 trip。

    口径：每单元贡献 = `record.prompt_tokens + record.tokens_used`：
    - `prompt_tokens` 用**真值**（⑦；usage 透出。dry-run 无 usage ⇒ 0）；
    - completion 用循环自己的记账 `tokens_used`（真值优先、估算兜底，见 `completion_tokens_of`）
      —— 这样 `--dry-run`（无 usage、走估算）下闸也**真的会动**（可测，不是真空闸）。
    `--max-total-tokens` / `--max-est-cost` 为 0 ⇒ 该项不设限（默认两条都不限）。
    """

    def __init__(self, *, max_total_tokens: int = 0, max_est_cost: float = 0.0) -> None:
        self._max_total_tokens = max_total_tokens
        self._max_est_cost = max_est_cost
        self.total_tokens = 0
        self.est_cost = 0.0

    def add(self, record: RunRecord) -> None:
        """累计一个单元的 token 与估算成本。"""
        tokens = record.prompt_tokens + record.tokens_used
        self.total_tokens += tokens
        self.est_cost += tokens / 1000.0 * EST_COST_PER_1K_TOKENS_USD

    @property
    def tripped(self) -> bool:
        """是否越限（token 或成本任一触顶）。"""
        if self._max_total_tokens > 0 and self.total_tokens >= self._max_total_tokens:
            return True
        return self._max_est_cost > 0 and self.est_cost >= self._max_est_cost

    @property
    def reason(self) -> str | None:
        """触顶原因（非泄值人话；未触顶 ⇒ None）。"""
        if self._max_total_tokens > 0 and self.total_tokens >= self._max_total_tokens:
            return f"累计 token {self.total_tokens} ≥ 上限 {self._max_total_tokens}"
        if self._max_est_cost > 0 and self.est_cost >= self._max_est_cost:
            return (
                f"估算成本 {self.est_cost:.4f}$ ≥ 上限 {self._max_est_cost}$"
                "（单价 UNVERIFIED：本仓无价目表，见 EST_COST_PER_1K_TOKENS_USD）"
            )
        return None


class JsonlRunStore:
    """① 逐篇增量落盘：每（篇 × 臂）一行 JSONL（`record_to_dict` 形状）+ flush + fsync。

    为什么每行 flush+fsync：一次瞬断最多丢**当前这一行**（否则整个实验白跑，连残值都拿不到 ——
    这正是计划 ① 要消灭的"一次瞬断即全损"）。
    `resume=True` 时读回既有行并据此跳过已落盘单元（`(case_id, arm)` 粒度 ⇒ 重跑**幂等**：
    重复运行不新增任何行）。
    """

    def __init__(self, path: str, *, resume: bool = False) -> None:
        self._path = path
        self._records: list[RunRecord] = []
        self._done: set[tuple[str, str]] = set()
        if resume and os.path.exists(path):
            for record in _read_jsonl_records(path):
                self._records.append(record)
                self._done.add((record.case_id, record.arm.value))

    def is_done(self, case_id: str, arm: Arm) -> bool:
        """该（篇 × 臂）单元是否已落盘（`--resume` 的跳过判据）。"""
        return (case_id, arm.value) in self._done

    def append(self, record: RunRecord) -> None:
        """落盘一行（append + flush + fsync）并纳入内存记录集。"""
        parent = os.path.dirname(os.path.abspath(self._path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record_to_dict(record), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._records.append(record)
        self._done.add((record.case_id, record.arm.value))

    @property
    def records(self) -> list[RunRecord]:
        """已落盘的全部记录（既有 + 本次新增）—— 续跑后用它出报告。"""
        return list(self._records)


def _read_jsonl_records(path: str) -> list[RunRecord]:
    """读回 JSONL（跳过空行）；损坏行大声失败（不猜、不静默丢 —— 丢了会让续跑重复记账）。"""
    records: list[RunRecord] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(_record_from_dict(json.loads(text)))
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"JSONL 第 {line_number} 行损坏（{path}）：{exc}") from exc
    return records


def _failed_record(case: SeedCase, arm: Arm, *, chat: ChatFn, reason: str) -> RunRecord:
    """② 重试耗尽的失败单元记录：`status="failed"`、`final_text=原文`（未改）、`reason="failed: …"`。

    为什么不抛、继续：一次瞬断不再让整轮实验白跑（计划 ②）。为什么 `final_text=原文`：该单元
    没有产出任何新文本，"没改" 是如实记录（而不是空串/伪造文本 —— 那才会让记账失真）。
    """
    return RunRecord(
        arm=arm,
        case_id=case.id,
        final_text=case.text,
        rounds=0,
        reason=f"failed: {reason}",
        converged=False,
        tokens_used=0,
        elapsed_s=0.0,
        model=str(getattr(chat, "model_name", "")),
        last_candidate_text=None,
        temperature=float(getattr(chat, "temperature", EXPERIMENT_TEMPERATURE)),
        prompt_tokens=0,
        completion_tokens=0,
        estimated_completion_tokens=0,
        status="failed",
    )


def _run_units(
    cases: Sequence[SeedCase],
    make_chat: Callable[[SeedCase, Arm], ChatFn],
    *,
    store: JsonlRunStore | None,
    cost_gate: CostGate | None,
    allow_fail: bool,
    feedback: bool = False,
) -> list[RunRecord]:
    """单元执行器（① 增量落盘 + ② 失败继续 + ⑤ 成本闸 的**唯一收口**）。

    - `store` 非空 ⇒ 跳过已落盘单元、每单元落盘一行；
    - `allow_fail` ⇒ 捕获**可重试**错误（429/5xx/传输层）并标 failed 继续（不可重试错误原样冒泡）；
    - `cost_gate` 非空 ⇒ 每单元后累计；越限即**停止**（返回已跑的部分记录，由调用方映射为
      `EXIT_COST_CAP` —— 触顶即停，但已完成的部分**如实保留**，不静默丢弃）。
    - `feedback` ⇒ 是否开启裁判结论回灌通道（默认 False 维持 ADR-0024 准入式基线）。
    """
    records: list[RunRecord] = []
    stop = False
    for case in cases:
        if stop:
            break
        for arm in Arm:
            if store is not None and store.is_done(case.id, arm):
                continue
            chat = make_chat(case, arm)
            try:
                record = run_arm(case, arm, chat=chat, feedback=feedback)
            except Exception as exc:  # 宽捕是刻意的：只对可重试错误吞并标 failed，其余原样重抛
                if not (allow_fail and _is_retryable_llm_error(exc)):
                    raise
                record = _failed_record(case, arm, chat=chat, reason=str(exc))
            records.append(record)
            if store is not None:
                store.append(record)
            if cost_gate is not None:
                cost_gate.add(record)
                if cost_gate.tripped:
                    stop = True
                    break
    return records


def run_dry_run(
    cases: Sequence[SeedCase],
    *,
    store: JsonlRunStore | None = None,
    cost_gate: CostGate | None = None,
    feedback: bool = False,
) -> list[RunRecord]:
    """按「逐篇轮转」次序跑完全部用例 × 三臂（设计稿 §3.2 的交错执行；输出顺序确定）。

    `store` / `cost_gate` 可选（① / ⑤）；dry-run 单元不会失败（stub 确定性）⇒ `allow_fail=False`。
    每臂取**新鲜**的 stub chat（脚本计数器逐臂复位）。
    `feedback` ⇒ 是否启用裁判结论回灌（默认 False）。
    """
    return _run_units(
        cases,
        lambda case, _arm: build_dry_run_chat(case),
        store=store,
        cost_gate=cost_gate,
        allow_fail=False,
        feedback=feedback,
    )


# --------------------------------------------------------------------------- #
# Task 3：测量与综合记账（判决量 = held-out 种子回收率；成本/延迟/轮数）
# --------------------------------------------------------------------------- #

#: 判决量名（`Report["judgement_basis"]`）：判决只来自 held-out 种子回收率（仪器 A）。
#: MUST NOT 被任何 LLM 评分替换（`AGENT-EVALUATION-HARNESS` §1 / `AGENT-CONDUCT` §10.2；有测试钉住）。
JUDGEMENT_BASIS = "uncovered_seed_recovery"

#: `summarize` 的 Report 形状（JSON 友好 dict；Task 4 起含 `auxiliary` 槽，默认 None =
#: 盲评 rater（`tools/bench_judge_rater.py`）未运行 —— 它是该槽唯一的写入面，且
#: `judgement_basis` 与 `arms` 里的判决字段 MUST NOT 被任何后续任务改写；Task-4b 起每臂
#: 另含两个**附带指标**（`R_uncovered_last_candidate` / `candidates_recorded`，不进判决）。
Report = dict[str, Any]


def _score_uncovered_text(text: str, case: SeedCase) -> int:
    """held-out 回收的 **text 级口径**（`score_uncovered` 与 Task-4b 候选口径**逐字共用**）。

    逐处口径（不是整句相等），每处 probe 注入：
    - `wrong` 在 `text` 中出现 ≥1 次 ⇒ 该处记 0（错形残留，即使 `right` 也出现了）；
    - 否则记 `min(right 出现次数, expected_count)` —— `clean_text` 里 `right` 恰好出现
      `expected_count` 次 ⇒ 多出的出现属自由发挥，不额外计分。
    `signal` 只是「点火器」（让 A3 真迭代），MUST NOT 计入本口径（有测试钉住）。

    提为独立函数而不是两处各写一遍：final 与 last-candidate 两个口径 MUST 同源，
    任何一处漂移（如封顶/残留条件改动）都会让「回退掩盖」的对比数字失真。
    """
    recovered = 0
    for injection in case.injections:
        if injection.kind != "probe":
            continue
        if text.count(injection.wrong) > 0:
            continue
        recovered += min(text.count(injection.right), injection.expected_count)
    return recovered


def _probe_places(case: SeedCase) -> int:
    """一篇种子的 probe 处数（Σ `expected_count`；signal 不计）—— 回收率两个口径的共同分母。"""
    return sum(injection.expected_count for injection in case.injections if injection.kind == "probe")


def score_uncovered(record: RunRecord, case: SeedCase) -> int:
    """判决量分子：`record.final_text` 中 **probe** 注入被回收的处数（signal 永不进判决量）。

    实现委托 `_score_uncovered_text` —— 与 Task-4b 的 last-candidate 附带指标**逐字同源**
    （口径：probe-only、`wrong` 残留归零、`right` 按 `expected_count` 封顶）。
    """
    return _score_uncovered_text(record.final_text, case)


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
    - **Task-4b 附带指标**（进报告、**MUST NOT 进 P1/P2 判决**；设计稿 2026-10-16 修订段）：
      `R_uncovered_last_candidate` = 「回退前最后候选」（`record.last_candidate_text`）的
      池化回收率，**仅池化于「有候选」的记录**（Σ候选回收 / Σ有候选记录的 probe 处数；
      口径与 `R_uncovered` 共用一个 text 级函数）；`candidates_recorded` = 有候选记录数。
      某臂零条有候选记录 ⇒ `0.0` + `0`（不得除零）。

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
                "R_uncovered_last_candidate": 0.0,
                "candidates_recorded": 0,
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
        candidate_recovered = 0
        candidate_probes_places = 0
        candidates_recorded = 0
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
            places = _probe_places(case)
            probes_places += places
            # Task-4b 附带指标：仅「有候选」记录进候选池化（分母同样只含这些记录的 probe 处数）。
            if record.last_candidate_text is not None:
                candidates_recorded += 1
                candidate_recovered += _score_uncovered_text(record.last_candidate_text, case)
                candidate_probes_places += places
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
            "R_uncovered_last_candidate": (
                candidate_recovered / candidate_probes_places if candidate_probes_places > 0 else 0.0
            ),
            "candidates_recorded": candidates_recorded,
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
# Task-5a：真跑接线（--real）—— 运行期环境 / 真 chat（生产同形）/ 真跑驱动
# --------------------------------------------------------------------------- #

#: 无 Key 的人话原因（真跑前置失败 ⇒ 退出码 2）。MUST NOT 携带 key 本体（或任何凭据片段）。
_NO_KEY_REASON = (
    "未检测到 API Key（key 存在=False）：请先在应用设置（或 .env）配置后重试；"
    "零 Key 场景请用 --dry-run（本模式绝不静默回退）"
)


class RealRunUnavailable(RuntimeError):
    """`--real` 前置不满足（无 Key）⇒ 调用方映射为「环境不可用，退出码 2」。

    只承载**非泄值**原因：MUST NOT 携带 Key 本体或任何凭据片段（有测试用假 key 全程 tripwire）。
    """


def _ensure_runtime_env() -> None:
    """`--real` 分支**唯一**的运行期环境载入点（与生产同源：`delector.server.load_env`）。

    为什么调生产自己的 `load_env` 而不是在 harness 里复刻 .env 解析：凭据载入口径 MUST 单源
    （复刻即引入「生产能读到的 .env、实验读不到」的漂移面）。本函数只被 `--real` 分支调用
    —— `--dry-run` 全链路绝不触它（有测试用「调用即 fail」的 stub 钉住），dry-run 的
    「零 Key、不出网」不变量因此仍是产物级成立的。
    """
    from delector.server import load_env

    load_env()


def _effective_api_key() -> str:
    """当前生效 API Key（**值绝不外传**：唯一消费者 = `RealChat` 构造；对外只报布尔）。

    走 `llm_client` 的判定面（应用唯一出网口；与 `chat()` 内部取 key 的解析同源）。用
    `getattr` 取模块属性而不是显式 import：`llm_client` 对这两个名字是裸 re-export，显式
    import 会被 `mypy --strict`（no_implicit_reexport）判 attr-defined；`getattr` 保持
    「取值面 = llm_client（测试可以该面 monkeypatch）」且类型门禁干净。
    """
    from delector.services import llm_client

    return str(getattr(llm_client, "get_effective_api_key")())


def _effective_api_base_url() -> str:
    """当前生效 API base_url（同 `_effective_api_key` 的取值面；真 chat 构造期一次读取）。"""
    from delector.services import llm_client

    return str(getattr(llm_client, "get_effective_api_base_url")())


def _effective_api_model() -> str:
    """当前生效模型名（生产同款取值面；真 chat 的出网 `model` 与此读取面同源）。"""
    from delector.core.database import get_effective_api_model

    return str(get_effective_api_model())


def _is_retryable_llm_error(exc: Exception) -> bool:
    """② 可重试判据：429 / 5xx / **传输层**（`status_code is None`）⇒ True；其余（401/402/400…）⇒ False。

    chat 无副作用 ⇒ 重试幂等。不可重试错误（凭据 / 额度 / 参数类）继续跑也没意义 ⇒ 立即冒泡。
    """
    from delector.services import llm_client

    if not isinstance(exc, llm_client.LLMError):
        return False
    status = exc.status_code
    if status is None:
        return True
    return status == 429 or 500 <= status < 600


def _jitter(upper: float) -> float:
    """② 退避的 jitter（0..upper 均匀）：抽成模块函数便于测试注入确定性值（默认不死等）。"""
    return random.uniform(0.0, upper)


class RealChat:
    """真跑 chat：与 `routes.main._PolishReplyRecorder`（ai-polish 生产构造）**逐参同形**。

    生产链路（`routes/main.py`）：
        key = get_effective_api_key()；recorder = _PolishReplyRecorder(key, base_url.rstrip("/"))
        循环 → recorder(messages=…, model="", timeout=per_call, max_tokens=cap, response_format=…)
        recorder → llm_client.chat(messages, model=get_effective_api_model(), timeout, max_tokens,
                                   response_format, api_key=key, base_url=…)

    本类逐参一致（含「循环传入的空串 model 被忽略、以生效模型名出网」这条既有约定）；
    Task 4 增三处（各有测试钉住）：
    - **temperature 显式钉定**（③）：构造期接受（默认 `EXPERIMENT_TEMPERATURE`），每次出网带上；
    - **opt-in usage 透出**（⑦）：`include_usage=True` ⇒ 回复带 `usage`（真 prompt/completion token）；
    - **有界重试**（②）：429/5xx/传输层错 ≤ `MAX_RETRIES` 次、指数退避 + jitter；不可重试错立即冒泡。
    新增读取面 = `model_name` / `temperature` / `key_present` 三个**非泄值**属性（`RunRecord.model` /
    `RunRecord.temperature` 的取值来源与真跑前的布尔报告）。无状态 ⇒ 全实验共用一枚实例
    （harness 侧的每局记录由 `_ChatRecorder` 承担）。`sleep` 仅测试注入（避免真睡）。
    纪律：key / base_url 只在本实例内保存，任何输出 / 异常 / 日志都不带它们。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        temperature: float = EXPERIMENT_TEMPERATURE,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self._sleep = sleep if sleep is not None else asyncio.sleep

    @property
    def key_present(self) -> bool:
        """key 存在布尔（**非泄值判定面**：只归约成布尔，绝不回显 key 本体）。"""
        return bool(self._api_key)

    @property
    def model_name(self) -> str:
        """生效模型名（`RunRecord.model` 的取值来源；非泄值面）。"""
        return _effective_api_model()

    @property
    def temperature(self) -> float:
        """钉定的采样温度（`RunRecord.temperature` 的取值来源；非泄值面）。"""
        return self._temperature

    async def __call__(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str,
        timeout: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        from delector.services import llm_client

        # 循环传入的 `model` 为空串（「注入 chat 时循环不读配置」的既有约定）⇒ 与生产一致，
        # 以生效模型名出网；timeout / max_tokens / response_format 原样透传。Task 4：**temperature
        # 钉定**（③）与 **usage 透出**（⑦）一并带上。
        # ② 有界重试：只对 429/5xx/传输层错、≤ MAX_RETRIES 次、指数退避 + jitter；不可重试错立即冒泡。
        attempt = 0
        while True:
            try:
                return await llm_client.chat(
                    messages=messages,
                    model=_effective_api_model(),
                    timeout=max(timeout, 15.0),
                    max_tokens=max_tokens,
                    response_format=response_format,
                    temperature=self._temperature,
                    include_usage=True,
                    api_key=self._api_key,
                    base_url=self._base_url,
                )
            except llm_client.LLMError as exc:
                if attempt >= MAX_RETRIES or not _is_retryable_llm_error(exc):
                    raise
                await self._sleep(RETRY_BASE_DELAY_S * (2 ** attempt) + _jitter(RETRY_BASE_DELAY_S))
                attempt += 1


def build_real_chat(*, temperature: float = EXPERIMENT_TEMPERATURE) -> RealChat:
    """构造真 chat（生产同形）：key / base_url 均在构造期读取一次（同 `_PolishReplyRecorder`）。

    无 Key ⇒ `RealRunUnavailable`（人话原因；`--real` 绝不静默回退到 dry 桩）。`temperature`
    默认为实验钉定值（③）；`sleep` 留默认（真跑按退避真睡）。
    """
    key = _effective_api_key()
    if not key:
        raise RealRunUnavailable(_NO_KEY_REASON)
    return RealChat(api_key=key, base_url=_effective_api_base_url().rstrip("/"), temperature=temperature)


def run_connectivity_precheck() -> None:
    """④ `--real` 连通预检：正式跑之前发**一次**最小 chat（`parse_json=False`、`max_tokens=5`）。

    为什么单列一步：整轮真跑很贵，若 key / 网络根本不通，应在**任何样本消耗之前**快速失败。
    成功 ⇒ 返回 None；任何 `LLMError`（含传输层）⇒ `RealRunUnavailable`（调用方退 2）。
    单次有界（`CONNECTIVITY_PRECHECK_TIMEOUT_S`）—— 反挂死红线：任何网络调用 MUST 有超时。
    """
    from delector.services import llm_client

    key = _effective_api_key()
    base = _effective_api_base_url().rstrip("/")
    model = _effective_api_model()

    async def _once() -> dict[str, Any]:
        return await llm_client.chat(
            messages=[{"role": "user", "content": "ping"}],
            model=model,
            timeout=CONNECTIVITY_PRECHECK_TIMEOUT_S,
            max_tokens=llm_client.CONNECTIVITY_MAX_TOKENS,
            parse_json=False,
            api_key=key,
            base_url=base,
        )

    try:
        asyncio.run(_once())
    except llm_client.LLMError as exc:
        raise RealRunUnavailable(
            f"连通预检失败：{exc.detail}（status={exc.status_code}）；"
            "--real 在样本消耗之前失败 ⇒ 退出 2"
        ) from exc


def run_real(
    cases: Sequence[SeedCase],
    *,
    chat: ChatFn,
    store: JsonlRunStore | None = None,
    cost_gate: CostGate | None = None,
    feedback: bool = False,
) -> list[RunRecord]:
    """真跑：与 `run_dry_run` **同一次序**（逐篇三臂交错）跑完全部用例，驱动源 = 真 chat。

    ② 失败语义：**可重试**错误（429/5xx/传输层）在 `RealChat` 内重试耗尽后，本层把该单元标
    `status="failed"` 并**继续**下一篇（一次瞬断不再让整轮白跑）；**不可重试**错误仍原样冒泡
    ⇒ 调用方显式退 2。① 增量落盘 / ⑤ 成本闸由共享执行器 `_run_units` 承担。
    `feedback` ⇒ 是否启用裁判结论回灌（默认 False）。
    """
    return _run_units(
        cases,
        lambda _case, _arm: chat,
        store=store,
        cost_gate=cost_gate,
        allow_fail=True,
        feedback=feedback,
    )


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


def _print_text_report(
    records: Sequence[RunRecord],
    report: Report,
    *,
    real: bool = False,
    feedback: bool = False,
) -> None:
    """文本模式：逐条原始记录（只报比例无法复核，故全量打印）+ 每臂汇聚行 + 【综合记账】（Task 3）。

    `real` 只影响**如实标注**的两行（模式与驱动源）：`--real` 的真跑头行 MUST NOT 复读
    dry-run 的「零 Key、不出网」字样；记录与记账面两模式同构。
    """
    mode = "--real 真跑（真实 llm_client.chat；有界重试；temperature 钉定）" if real else "--dry-run 全链路"
    fb_label = (
        "feedback=enabled（回灌模式 Verifier-in-the-Loop）"
        if feedback
        else "feedback=disabled（无回灌准入基线）"
    )
    print(f"=== bench_judge_gaming（§4.3 第 8 条对照实验 · 三臂 harness · {mode} · {fb_label}）===")
    models = sorted({record.model for record in records})
    print(f"模型={models or ['（无记录）']}；temperature 钉定={EXPERIMENT_TEMPERATURE}")
    print(NO_SEED_FACT_STATEMENT)
    fb_status = "enabled" if feedback else "disabled"
    if real:
        print(f"records={len(records)}（逐篇三臂交错；真 chat 驱动；feedback={fb_status}；记录与记账口径同 --dry-run）")
    else:
        print(f"records={len(records)}（逐篇三臂交错；stub chat 按轮次预构造；feedback={fb_status}；零 Key、不出网）")
    for record in records:
        print(
            f"[{record.case_id}] {record.arm.value}: status={record.status} rounds={record.rounds} "
            f"reason={record.reason} converged={record.converged} tokens={record.tokens_used} "
            f"prompt={record.prompt_tokens} completion={record.completion_tokens} "
            f"est_completion={record.estimated_completion_tokens} "
            f"elapsed={record.elapsed_s:.3f}s model={record.model} temp={record.temperature}"
        )
    print()
    for arm in Arm:
        subset = [record for record in records if record.arm is arm]
        converged = sum(1 for record in subset if record.converged)
        print(f"[{arm.value}] runs={len(subset)} converged={converged}")
    print()
    print(
        f"【综合记账】judgement_basis={report['judgement_basis']}"
        "（判决量 = held-out 种子回收率 R_uncovered；R_judge 为旁证；"
        "R_uncovered_last_candidate / candidates_recorded 为附带指标、不进判决；LLM 评分不进此表）"
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
        print(
            f"[{arm.value}] R_uncovered_last_candidate={metrics['R_uncovered_last_candidate']:.3f} "
            f"candidates_recorded={metrics['candidates_recorded']}"
            "（附带指标，不进 P1/P2 判决；仅池化于「有候选」记录）"
        )
    print()
    print("退出码：0=完成；1=样本集无效（空集/缺 signal/缺 probe/注入破损）；")
    print(
        "        2=环境不可用或真跑失败（依赖链 import 失败 / 德语模型不可用 / 无 Key / "
        "连通预检失败 / 有失败单元）；"
    )
    print(f"        {EXIT_COST_CAP}=成本硬闸触顶（--max-total-tokens / --max-est-cost）。")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口。退出码：0=完成；1=样本集无效；2=环境不可用。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：德语字符需 UTF-8
        except Exception:  # 已关闭/不可重配置的流（如 pytest capture）⇒ 保持原状
            pass

    parser = argparse.ArgumentParser(
        description="§4.3 第 8 条对照实验的三臂 harness（--dry-run 零 Key 全链路；--real 真跑 HITL）。"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="用确定性 stub chat 驱动 run_polish_loop 全链路（零 Key、不出网）",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="真跑（HITL）：载入运行时凭据逐条经 llm_client.chat 出网（会烧配额）；连通预检 + 有界重试",
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
        help="只跑 SEED_CASES 的前 N 篇（N ≥ 1；顺序冻结、确定性；与 --dry-run / --real 同用）",
    )
    parser.add_argument(
        "--save",
        default=None,
        metavar="PATH",
        help="① 逐篇增量落盘的 JSONL 路径（每（篇 × 臂）一行，flush+fsync）",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="① 从 --save 的 JSONL 续跑：已落盘单元跳过，只补缺（幂等）",
    )
    parser.add_argument(
        "--max-total-tokens",
        type=int,
        default=0,
        metavar="N",
        help=f"⑤ 成本硬闸：累计 (prompt+completion) token 上限（0=不限）；触顶停并退 {EXIT_COST_CAP}",
    )
    parser.add_argument(
        "--max-est-cost",
        type=float,
        default=0.0,
        metavar="USD",
        help=f"⑤ 成本硬闸：估算成本上限（美元；0=不限；单价 UNVERIFIED）；触顶停并退 {EXIT_COST_CAP}",
    )
    parser.add_argument(
        "--feedback",
        action="store_true",
        help="启用裁判结论回灌通道（Verifier-in-the-Loop）",
    )
    parser.add_argument(
        "--no-feedback",
        action="store_true",
        help="禁用裁判结论回灌通道（默认，维持 ADR-0024 准入式基线）",
    )
    args = parser.parse_args(argv)

    if args.feedback and args.no_feedback:
        parser.error("--feedback 与 --no-feedback 互斥：不能同时指定")

    if args.cases is not None and args.cases < 1:
        parser.error(f"--cases 必须 ≥ 1（取 SEED_CASES 前 N 篇口径），收到 {args.cases}")

    if args.resume and args.save is None:
        parser.error("--resume 需要 --save PATH（续跑的落盘仓从它读回已跑单元）")

    if args.max_total_tokens < 0:
        parser.error(f"--max-total-tokens 必须 ≥ 0（0=不限），收到 {args.max_total_tokens}")

    if args.max_est_cost < 0:
        parser.error(f"--max-est-cost 必须 ≥ 0（0=不限），收到 {args.max_est_cost}")

    if args.dry_run and args.real:
        parser.error("--dry-run 与 --real 互斥：两种驱动源只能选一种")

    if not args.dry_run and not args.real:
        print(
            "[用法错误] 未指定运行模式：需 --dry-run 或 --real"
            "（--dry-run = 零 Key stub 链；--real = 真实出网、会烧配额，属 HITL）。",
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

        # ① 落盘仓（可选）：`--save` 给路径；`--resume` 从它读回已跑单元并跳过。
        store: JsonlRunStore | None = None
        if args.save is not None:
            try:
                store = JsonlRunStore(args.save, resume=args.resume)
            except (OSError, ValueError) as exc:
                print(f"[环境不可用] JSONL 记录仓不可用：{exc}", file=sys.stderr)
                return 2
        # ⑤ 成本硬闸（默认两条都不限 ⇒ 不改变既有行为）。
        cost_gate = CostGate(max_total_tokens=args.max_total_tokens, max_est_cost=args.max_est_cost)

        if args.real:
            # Task-5a 真跑接线：运行期环境载入（唯一调用点）→ 真 chat 构造（生产同形）
            # → ④ 连通预检（正式跑之前）→ 真跑。
            from delector.services import llm_client

            try:
                _ensure_runtime_env()
                real_chat = build_real_chat()
                model_name = _effective_api_model()
                run_connectivity_precheck()
            except RealRunUnavailable as exc:
                print(f"[真跑不可用] {exc}", file=sys.stderr)
                return 2
            except Exception as exc:  # 依赖链 / 配置读取不可用 ⇒ 归「环境不可用」
                print(f"[真跑不可用] 运行期依赖装载失败：{type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            # 真跑前的**非泄值**事实行：只报布尔与模型名 —— 绝不打印 key 本体（红线）。
            print(
                f"[真跑] key 存在={real_chat.key_present}；生效模型={model_name}；"
                f"temperature 钉定={real_chat.temperature}；"
                f"样本 {len(cases)} 篇 × 3 臂 = {len(cases) * 3} 局；"
                "单次 chat 超时 = 循环生产口径（min(30.0s, 剩余 deadline)）、有界重试（≤2 次）",
                file=sys.stderr,
            )
            try:
                records = run_real(
                    cases,
                    chat=real_chat,
                    store=store,
                    cost_gate=cost_gate,
                    feedback=args.feedback,
                )
            except llm_client.LLMError as exc:
                # **不可重试**（或预检之外）的上游失败 ⇒ 显式退 2（1 是样本集无效，不复用）。
                # 只透 `detail`（固定人话）、不透 `raw`（可能带凭据）。
                print(
                    f"[真跑失败] 上游 LLM 调用异常：{exc.detail}（status={exc.status_code}）；退出码 2",
                    file=sys.stderr,
                )
                return 2
        else:
            records = run_dry_run(
                cases,
                store=store,
                cost_gate=cost_gate,
                feedback=args.feedback,
            )

    if store is not None:
        records = store.records  # 续跑：报告覆盖既有 + 本次新增
    failed = [record for record in records if record.status != "ok"]
    if args.json:
        print(json.dumps([record_to_dict(record) for record in records], ensure_ascii=False, indent=2))
    else:
        _print_text_report(records, summarize(records, cases), real=args.real, feedback=args.feedback)
    if cost_gate.tripped:
        # ⑤ 触顶即停：已完成的部分已如实打印/落盘；用**独立退出码**区分于 0/1/2。
        print(f"[成本硬闸] {cost_gate.reason}（退出码 {EXIT_COST_CAP}）", file=sys.stderr)
        return EXIT_COST_CAP
    if failed:
        print(
            f"[真跑告警] {len(failed)} 个单元重试耗尽被标 failed（已记录并继续下一篇）。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
