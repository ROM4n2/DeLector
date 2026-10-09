# -*- coding: utf-8 -*-
"""复用 Task 1–4 基准，一条命令输出 ADR-0018 §6 分层汇总。

Task 5b 的三条硬纪律（改这个文件前务必先读）
------------------------------------------
1. **p95 不许用中位数冒充**：四场景 p95 一律取上游基准的 `*_p95_ms`（与中位数同批
   样本），上游缺失时输出 `unmeasured`，绝不拿 `scenario_*_s`（中位数）折算。
2. **样本量不足不许写强结论**：n<20 时 p95 系统性低估尾部（n=5 的经验 p95≈最大值，
   P(max₅ < 真p95) = 0.95⁵ ≈ 77%）⇒ 条件② 只能写「仅可否证（未能确证不成立）」，
   **不许**写「不成立」；只有 n≥20 才允许下强结论。见 `tools/bench_stats.py`。
3. **目标值已拍板但仍须绑定阅读**：`target_status=confirmed`（2026-10-09 用户拍板，性质为
   价值判断 / 体验预算，无客观对错）。所有 `headroom_to_2x_target_*` 必须与它绑定阅读 ——
   目标一变余量即变，拆开搬运的数字会被下游当成客观事实写进 ADR。
4. **热读是缓存哨兵**：`warm_read` 只验证缓存生效（µs 级 dict 命中 vs 0.1s 目标差 4 个数量级），
   **不参与条件②** —— 判定集恰 3 场景（cards_list / long_read_cold / cold_start），见门禁。

用法::

    export PYTHONIOENCODING=utf-8
    python tools/bench_profile_layers.py                 # 默认档（沿用各基准原轮数）
    BENCH_P95_ROUNDS=20 python tools/bench_profile_layers.py   # 人工档：把 p95 样本量提到 n=20
"""

import importlib
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Protocol, Sequence, Tuple, cast

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
TIMEOUT_S = 900

TARGET_COLD_START_S = 2.0
TARGET_LONG_READ_COLD_S = 1.5
TARGET_CARDS_LIST_S = 1.0
TARGET_WARM_READ_S = 0.1
# 目标值来源＝用户拍板（2026-10-09），性质＝**价值判断**（体验预算，无客观对错）。
# 联动警示必须保留：目标一变，条件②与 headroom 一起变 —— 不得把余量数字拆开单独引用。
TARGET_SOURCE = (
    "来源＝用户拍板（2026-10-09）；本值的性质是价值判断（体验预算，无客观对错），"
    "不是可推导的物理量；条件②的成立与否完全依赖这组值，目标一变则结论（含 headroom）即变"
)
# 已拍板，但仍必须作为一行随数字一起输出：headroom 与条件②都随它联动，
# 脱离这一行单独引用余量数字 = 把"体验预算"当客观事实。
TARGET_STATUS_NOTE = (
    "target_status=confirmed（2026-10-09 用户拍板）：四项目标值已确认，其性质是价值判断"
    "（体验预算，无客观对错）；headroom_to_2x_target_* 与条件②的结论仍随目标值联动"
    "（目标一变结论即变），禁止脱离本行单独引用余量数字"
)

# 条件② 的判定门：p95 > 2×目标（ADR-0018 §6）。
TWO_X_TARGET_S = {
    "cards_list": TARGET_CARDS_LIST_S * 2.0,
    "long_read_cold": TARGET_LONG_READ_COLD_S * 2.0,
    "warm_read": TARGET_WARM_READ_S * 2.0,
    "cold_start": TARGET_COLD_START_S * 2.0,
}
# 条件② 的判定场景集：**恰 3 场景**。warm_read 已被移出 —— 它是缓存哨兵（只证明缓存生效，
# µs 级 dict 命中 vs 0.1s 目标差 4 个数量级），不构成"架构需改造"的信号，留在判定集只会稀释门。
CONDITION_TWO_SCENARIOS: Tuple[str, ...] = ("cards_list", "long_read_cold", "cold_start")
# 缓存哨兵场景集：仍测量、仍输出，但**不参与条件②**（见 SENTINEL_NOTE）。
SENTINEL_SCENARIOS: Tuple[str, ...] = ("warm_read",)
SENTINEL_ROLE = "sentinel"
SENTINEL_NOTE = (
    "warm_read_role=sentinel：热读是**缓存哨兵**，只用于验证缓存生效（实测 µs 级 dict 命中）；"
    "它**不参与条件②**（已移出判定集），headroom_to_2x_target_warm_read 仅为对照、"
    "不得用于 O2/O3 之类的架构判定"
)


def _validate_scenario_partition() -> None:
    """启动期门禁：判定集恰 3 场景、哨兵恰 1 场景，两者互斥且合起来等于全部被测场景。

    防将来有人**悄悄把 warm_read 加回判定集**（它会永远"不超标"从而稀释门）或**漏掉某个
    判定场景**（会让条件②的口径在无人察觉下改变）。这不是装饰：断言在 import 期即执行。
    """
    two = set(CONDITION_TWO_SCENARIOS)
    sentinel = set(SENTINEL_SCENARIOS)
    if len(CONDITION_TWO_SCENARIOS) != 3:
        raise AssertionError(
            f"条件②判定集必须恰 3 场景，实际 {len(CONDITION_TWO_SCENARIOS)}：{CONDITION_TWO_SCENARIOS}"
        )
    if len(SENTINEL_SCENARIOS) != 1:
        raise AssertionError(
            f"哨兵场景集必须恰 1 场景，实际 {len(SENTINEL_SCENARIOS)}：{SENTINEL_SCENARIOS}"
        )
    if two & sentinel:
        raise AssertionError(f"判定集与哨兵集不得重叠：{two & sentinel}")
    if two | sentinel != set(TWO_X_TARGET_S):
        raise AssertionError(
            f"判定集 ∪ 哨兵集 != 全部被测场景：{two | sentinel} vs {set(TWO_X_TARGET_S)}"
        )
    if "warm_read" in two:
        raise AssertionError("warm_read 不得进入条件②判定集（它是缓存哨兵）")


_validate_scenario_partition()
# 上游基准的 p95 键（毫秒）→ 本脚本的场景名。**刻意只认 _p95_ms**：
# 若这里退化成读中位数键，条件② 就不再是 ADR 要求的口径。
P95_SOURCE_KEYS = {
    "cards_list": ("cards", "segment_D_p95_ms"),
    "long_read_cold": ("long_read", "cold_p95_ms"),
    "warm_read": ("long_read", "warm_p95_ms"),
    "cold_start": ("cold_start", "health_200_p95_ms"),
}
# 样本行（逗号分隔毫秒）→ 用来申报真实样本量 n；只报 p95 不报 n，下游会把它当已确证。
SAMPLES_SOURCE_KEYS = {
    "cards_list": ("cards", "samples_segment_D_ms"),
    "long_read_cold": ("long_read", "samples_cold_ms"),
    "warm_read": ("long_read", "samples_warm_ms"),
    "cold_start": ("cold_start", "samples_health_200_ms"),
}
# 强结论所需样本量：n<20 时 p95 低估尾部到"未超门限"不足以证否。
MIN_N_FOR_STRONG_VERDICT = 20

# 四场景均为**代理口径**（不是浏览器端到端），不声明就会被下游当端到端 p95 写进 ADR。
SCENARIO_SCOPE_NOTE = (
    "四场景均为代理口径、非浏览器端到端：cards_list=segment_D（进程内 SQL+物化+FSRS 段），"
    "不是『列表渲染+滚动』端到端；cold_start=health_200（/api/health 返回 200），不等于首屏可用；"
    "long_read_cold/warm_read=api_syntax_hard_sentences 的进程内调用，不含前端渲染与网络 ⇒ "
    "条件② 用的是代理值，回填 ADR 时不得写成端到端 p95"
)
# 逐路径事实（修正 Task 5 的错误理由：并非"为避免真发需 key/付费请求"）——
# 只有 AI 需 key；TTS/RSS 免 key。理由写错会原样搬进 ADR。
NETWORK_NOTE = (
    "逐路径事实：AI 需 DEEPSEEK_API_KEY（database.py:765 get_effective_api_key，缺 key 时 "
    "main.py 直接返回占位文案、根本不发请求）｜TTS 免 key（delector/services/tts.py 自实现的 "
    "Edge TTS 协议 / edge-tts，tools/build_embedded_audio.py 本就无 key 真发）｜RSS 是公开免 key "
    "预设源（delector/core/security.py:241-291 PRESET_FEEDS：tagesschau/DW/DLF/Spiegel/Zeit）；"
    "本基准是**选择**不发外部请求（避免 CI 外网抖动与第三方服务风险，而非『必须 key 才发不出来』），"
    "且四个被测场景均不走网络 ⇒ 网络层对本次四场景贡献为 0，故 network_pct=unmeasured 不影响判定门"
)


class ResourceUsage(Protocol):
    ru_maxrss: float


class ResourceModule(Protocol):
    RUSAGE_CHILDREN: int

    def getrusage(self, who: int) -> ResourceUsage: ...


@dataclass(frozen=True)
class BenchResult:
    name: str
    values: Dict[str, str]
    error: Optional[str]


def _one_line(text: str) -> str:
    return " ".join(text.split())[-1000:] or "无诊断输出"


def _run_benchmark(
    name: str,
    script_name: str,
    overrides: Mapping[str, str],
    required: Sequence[str],
) -> BenchResult:
    env = dict(os.environ)
    env.update(overrides)
    env["PYTHONIOENCODING"] = "utf-8"
    script = TOOLS / script_name
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return BenchResult(name, {}, _one_line(str(exc)))
    values = dict(re.findall(r"^([A-Za-z][A-Za-z0-9_]*)=(.*)$", proc.stdout, re.MULTILINE))
    if proc.returncode != 0:
        detail = proc.stderr or proc.stdout
        return BenchResult(name, values, f"退出码 {proc.returncode}：{_one_line(detail)}")
    missing = [key for key in required if key not in values]
    if missing:
        return BenchResult(name, values, f"输出缺少可解析行：{','.join(missing)}")
    return BenchResult(name, values, None)


def _number(result: BenchResult, key: str, suffix: str = "") -> Optional[float]:
    raw = result.values.get(key)
    if raw is None or (suffix and not raw.endswith(suffix)):
        return None
    candidate = raw[: -len(suffix)] if suffix else raw
    try:
        value = float(candidate)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _print_number(key: str, value: Optional[float], decimals: int, suffix: str = "") -> None:
    if value is None:
        print(f"{key}=unmeasured")
        return
    print(f"{key}={value:.{decimals}f}{suffix}")


def _rss_mb() -> Tuple[Optional[float], str]:
    if os.name == "nt":
        return None, "Windows 无 stdlib resource，且本任务不新增 psutil 依赖，故 RSS 峰值不可测"
    try:
        resource = cast(ResourceModule, importlib.import_module("resource"))
    except ImportError:
        return None, "当前平台无 stdlib resource，且本任务不新增 psutil 依赖，故 RSS 峰值不可测"
    peak = float(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return peak / divisor, "POSIX stdlib resource.RUSAGE_CHILDREN 的子进程峰值；未使用 psutil"


def _source_status(result: BenchResult) -> None:
    if result.error is None:
        print(f"source_bench_{result.name}=ok")
    else:
        print(f"source_bench_{result.name}=failed")
        print(f"source_bench_{result.name}_note={result.error}")


def _sample_count(result: BenchResult, key: str) -> Optional[int]:
    """从上游的样本行取真实样本数 n（不靠推断轮数：环境变量可能改过它）。"""
    raw = result.values.get(key)
    if not raw:
        return None
    items = [item for item in raw.split(",") if item.strip()]
    return len(items) or None


def _p95_seconds(sources: Mapping[str, BenchResult], scenario: str) -> Optional[float]:
    """取该场景的 p95（秒）。上游缺 p95 行 ⇒ None（届时由调用方输出 unmeasured）。"""
    source_name, key = P95_SOURCE_KEYS[scenario]
    ms = _number(sources[source_name], key)
    return None if ms is None else ms / 1000.0


def _condition_two(
    p95_s: Mapping[str, Optional[float]], p95_n: Optional[int]
) -> Tuple[str, str, Tuple[str, ...]]:
    """按 ADR-0018 §6 判定条件②（p95 > 2×目标），返回 (措辞, 明细, 超标场景元组)。

    判定集 = CONDITION_TWO_SCENARIOS（**恰 3 场景**）。warm_read 已被移出：它是缓存哨兵
    （µs 级 dict 命中 vs 0.1s 目标差 4 个数量级），只证明缓存生效，不构成"架构需改造"的信号。

    措辞纪律（**勿改**，越权即误判）
    ------------------------------
    - 缺任一**判定集**场景 p95 ⇒ `无法判定`（不给结论，也不给"看起来没超"的暗示）；
    - 任一判定场景 p95 > 2×目标 ⇒ `成立`：**低估方向对我们有利** —— n 小时 p95 系统性
      **低估**尾部，低估都超了，真值更超；
    - 全部未超 且 n < 20 ⇒ `仅可否证（未能确证不成立），需提高样本量`：低估方向对我们
      **不利**（可能只是没采到尾部），故不许写"不成立"；
    - 全部未超 且 n ≥ 20 ⇒ `不成立`（样本量已足以支撑强结论）。

    第三个返回值（超标场景元组）供 `_verdict` 做"修法路由"：门与修法不得错配。
    """
    # 只对**判定集**场景要求 p95：warm_read 缺失不影响条件②（它是哨兵，不参与判定）。
    missing = [name for name in CONDITION_TWO_SCENARIOS if p95_s.get(name) is None]
    if missing:
        return "无法判定", f"缺 {','.join(missing)} 的 p95（上游基准未输出该行）", ()
    measured: Dict[str, float] = {}
    ratios: Dict[str, float] = {}
    for name in CONDITION_TWO_SCENARIOS:
        value = p95_s[name]
        if value is None:  # 已由上面的 missing 拦截；此处仅收窄类型
            return "无法判定", f"缺 {name} 的 p95（上游基准未输出该行）", ()
        measured[name] = value
        ratios[name] = value / TWO_X_TARGET_S[name]
    detail = "；".join(
        f"{name} p95={measured[name]:.3f}s vs 2×目标 {TWO_X_TARGET_S[name]:.2f}s（余量 {ratios[name]:.2f}x）"
        for name in sorted(measured)
    )
    over = tuple(sorted(name for name in ratios if ratios[name] > 1.0))
    if over:
        return (
            "成立",
            f"{detail}；超门限场景 {','.join(over)}"
            f"（n={p95_n}；p95 在小样本下系统性**低估**尾部，低估都超 ⇒ 真值更超）",
            over,
        )
    if p95_n is None or p95_n < MIN_N_FOR_STRONG_VERDICT:
        return (
            "仅可否证（未能确证不成立），需提高样本量",
            f"{detail}；n={p95_n} 时 p95 系统性**低估**尾部（n=5 的经验 p95≈最大值，"
            f"P(max₅<真p95)=0.95⁵≈77%）⇒ 未超门限只能证否不了、不能确证不成立；"
            f"要下强结论须 BENCH_P95_ROUNDS≥{MIN_N_FOR_STRONG_VERDICT} 重跑（成本≈轮数线性）",
            (),
        )
    return (
        "不成立",
        f"{detail}；n={p95_n}≥{MIN_N_FOR_STRONG_VERDICT}，样本量已足以支撑强结论",
        (),
    )


def _route_for_over_limit(over: Sequence[str]) -> str:
    """条件②成立时，**按超标场景**给出对应的修法方向 —— 门与修法不能错配。

    真问题（产品席位指出）：唯一敏感场景是冷启动，而其瓶颈是 spaCy 模型加载 ≈1.47s
    （占首启 58%）= **初始化/IO**；O2（把 FSRS/排序等 CPU 热路径下沉到 Rust/Go）**修不了它**。
    故不能"条件②成立 ⇒ 直接建议 O2"，必须按超标场景分流。
    """
    if not over:
        # 空集是**内部误用**：本函数只在条件②「成立」时被调用，而"成立"蕴含至少一个场景超标。
        # 显式 raise 而非落到兜底的「建议O2评估」：否则未来有人直接传空集会拿到一个假的修法
        # 建议（把"没有超标场景"误读成"卡盒/长文超标"，把方向带偏）。中性文案会把误用悄悄放过。
        raise ValueError(
            "_route_for_over_limit 收到空的超标场景集：本函数仅在条件②成立（至少一个场景超标）"
            "时被调用；空集意味着判定门与修法路由被错接"
        )
    over_set = set(over)
    has_cold = "cold_start" in over_set
    has_hot = bool(over_set & {"cards_list", "long_read_cold"})
    if has_cold and has_hot:
        return (
            "建议：先做 O0 杠杆压冷启动（spaCy 惰性加载/延后模型加载），再评估 O2（热点下沉）"
            " —— 两者修的是不同瓶颈：冷启动是初始化/IO，卡盒/长文是 CPU 热路径"
        )
    if has_cold:
        return (
            "建议O0杠杆：spaCy 模型惰性加载/延后加载（直击首启模型加载 ≈1.47s、占首启 58%）；"
            "明说：O2（热点下沉）修不了它 —— 模型加载是初始化/IO，不是 CPU 热路径"
        )
    return (
        "建议O2评估（热点下沉）：超标场景（卡盒列表/长文冷读）是 CPU 热路径，"
        "可将 FSRS/排序等下沉到 Rust/Go"
    )


def _verdict(
    python_pct: Optional[float],
    p95_s: Mapping[str, Optional[float]],
    p95_n: Optional[int],
) -> str:
    two, two_detail, over = _condition_two(p95_s, p95_n)
    if python_pct is None:
        return (
            "条件①=无法判定（缺 Python 分层输入）；"
            f"条件②={two}（{two_detail}）；AND结果=无法判定；不足以判定；"
            "还缺可解析的 Python 分层输入"
        )
    if python_pct <= 50.0:
        return (
            f"条件①=不成立（加权 Python CPU 代理占比 {python_pct:.1f}% ≤ 50%）；"
            f"条件②={two}（{two_detail}）；AND结果=不成立；建议O0（双条件 AND 已因条件①不成立；"
            "仍可做便宜杠杆：惰性加载/缓存/预计算）"
        )
    if two == "成立":
        return (
            f"条件①=成立（加权 Python CPU 代理占比 {python_pct:.1f}% > 50%）；"
            f"条件②=成立（{two_detail}）；AND结果=成立；{_route_for_over_limit(over)}"
            "（ADR-0018 §6：双条件 AND 成立；但场景均为代理口径见 scenario_scope_note，"
            "目标值为价值判断见 target_status ⇒ 路线按本路由定稿）"
        )
    if two == "不成立":
        return (
            f"条件①=成立（加权 Python CPU 代理占比 {python_pct:.1f}% > 50%）；"
            f"条件②=不成立（{two_detail}）；AND结果=不成立；建议O0"
            "（双条件 AND 中条件②未成立；仍可做便宜杠杆；场景均为代理口径，见 scenario_scope_note）"
        )
    return (
        f"条件①=成立（加权 Python CPU 代理占比 {python_pct:.1f}% > 50%）；"
        f"条件②={two}（{two_detail}）；AND结果=无法判定；不足以判定；"
        f"还缺 n≥{MIN_N_FOR_STRONG_VERDICT} 的 p95 样本量（BENCH_P95_ROUNDS 提轮数即可，"
        "成本≈轮数线性），不能仅凭条件①建议 O2/O3"
    )


def _p95_note(p95_n: Optional[int], counts: Mapping[str, int]) -> str:
    """把 p95 的**统计口径与偏差方向**连同数字一起输出（不许只报数字）。"""
    detail = "；".join(f"{name}={count}" for name, count in sorted(counts.items())) or "无样本行"
    return (
        f"样本量 n={p95_n if p95_n is not None else 'unmeasured'}（逐场景 {detail}；由 BENCH_P95_ROUNDS 控制，"
        "默认沿用各基准原轮数，提高它不改代码、成本≈轮数线性）；"
        "分位方法 statistics.quantiles(sorted(samples), n=100, method='inclusive')[94]，"
        "与中位数取自**同一批**样本、不重新计时；"
        "偏差方向：n<20 时该分位系统性**低估**尾部（n=5 的经验 p95≈最大值，P(max₅<真p95)=0.95⁵≈77%）"
        "⇒ p95 未超门限只能『仅可否证（未能确证不成立）』、不得据此写『不成立』；"
        f"补测建议：判强结论请跑 BENCH_P95_ROUNDS={MIN_N_FOR_STRONG_VERDICT}（人工档），"
        "每轮=一次完整场景，冷启动档最贵（每轮一个全新解释器 + 一次起服务）"
    )


def main() -> int:
    cards = _run_benchmark(
        "cards_endpoint",
        "bench_cards_endpoint.py",
        {"BENCH_SCALES": "20000", "BENCH_ROUNDS": "5"},
        ("segment_B_ms", "segment_D_ms", "python_pct"),
    )
    spacy = _run_benchmark(
        "spacy_unit", "bench_spacy_unit.py", {"BENCH_SPACY_ROUNDS": "5"}, ("per_sentence_ms",)
    )
    long_read = _run_benchmark(
        "long_read",
        "bench_long_read.py",
        {"BENCH_LONG_READ_ROUNDS": "5"},
        ("cold_ms", "warm_ms", "spacy_pct"),
    )
    cold_start = _run_benchmark(
        "cold_start", "bench_cold_start.py", {"BENCH_COLD_START_ROUNDS": "5"}, ("health_200_ms",)
    )
    results = (cards, spacy, long_read, cold_start)
    sources: Dict[str, BenchResult] = {
        "cards": cards,
        "spacy": spacy,
        "long_read": long_read,
        "cold_start": cold_start,
    }
    print("=== bench_profile_layers ===")
    for result in results:
        _source_status(result)

    cards_total_ms = _number(cards, "segment_D_ms")
    cards_sql_ms = _number(cards, "segment_B_ms")
    cards_python_pct = _number(cards, "python_pct", "%")
    cold_ms = _number(long_read, "cold_ms")
    warm_ms = _number(long_read, "warm_ms")
    longread_python_pct = _number(long_read, "spacy_pct", "%")
    startup_ms = _number(cold_start, "health_200_ms")
    spacy_unit_ms = _number(spacy, "per_sentence_ms")

    weighted_python_pct: Optional[float] = None
    if (
        cards_total_ms is not None
        and cards_python_pct is not None
        and cold_ms is not None
        and longread_python_pct is not None
    ):
        denominator = cards_total_ms + cold_ms
        if denominator > 0.0:
            weighted_python_pct = (
                cards_python_pct * cards_total_ms + longread_python_pct * cold_ms
            ) / denominator
    sql_pct = None
    if cards_total_ms is not None and cards_total_ms > 0.0 and cards_sql_ms is not None:
        sql_pct = cards_sql_ms / cards_total_ms * 100.0

    _print_number("python_cpu_pct", weighted_python_pct, 1, "%")
    print(
        "python_cpu_weighting=(scenario_cards_python_pct×segment_D_ms + "
        "scenario_longread_python_pct×cold_ms)/(segment_D_ms+cold_ms)"
    )
    print("python_cpu_note=墙钟归因代理而非解释器采样；长文项含 spaCy C/Cython，跨口径总值仅供判定门输入")
    _print_number("sql_pct", sql_pct, 1, "%")
    print("sql_note=仅卡盒场景：segment_B_ms/segment_D_ms；长文与启动未单独切出 SQL")
    print("network_pct=unmeasured")
    print(f"network_note={NETWORK_NOTE}")
    _print_number("scenario_cards_python_pct", cards_python_pct, 1, "%")
    _print_number("scenario_longread_python_pct", longread_python_pct, 1, "%")
    print(
        "scenario_longread_python_note=来自 Task 3 spacy_pct；完整 NLP 管线与冷读端点跨口径，"
        "允许超过 100%，仅量级参考"
    )
    _print_number("scenario_cards_list_s", None if cards_total_ms is None else cards_total_ms / 1000.0, 3)
    _print_number("scenario_long_read_cold_s", None if cold_ms is None else cold_ms / 1000.0, 3)
    _print_number("scenario_warm_read_s", None if warm_ms is None else warm_ms / 1000.0, 6)
    startup_s = None if startup_ms is None else startup_ms / 1000.0
    _print_number("scenario_cold_start_s", startup_s, 2)
    _print_number("startup_s", startup_s, 2)
    _print_number("scenario_spacy_unit_per_sentence_ms", spacy_unit_ms, 3)

    # ---- p95（四场景）：只认上游的 *_p95_ms，缺即 unmeasured，绝不用中位数折算 ----
    p95_s = {scenario: _p95_seconds(sources, scenario) for scenario in P95_SOURCE_KEYS}
    # 6 位小数：热读是微秒级 dict 命中（p95≈19µs=0.000019s），4 位会打成 0.0000 —— 既像
    # "没测到"又过不了 `>0` 的输出契约；与 scenario_warm_read_s（同为 6 位）对齐。
    for scenario in ("cards_list", "long_read_cold", "warm_read", "cold_start"):
        _print_number(f"scenario_{scenario}_p95_s", p95_s[scenario], 6)
    counts: Dict[str, int] = {}
    for scenario, (source_name, key) in SAMPLES_SOURCE_KEYS.items():
        count = _sample_count(sources[source_name], key)
        if count is not None:
            counts[scenario] = count
    # n 取**判定集**（CONDITION_TWO_SCENARIOS）里**最小**的那个：判定门是 AND，最弱的一环决定
    # 能下多强的结论。**刻意不含哨兵 warm_read** —— 它不参与条件②，若把它的样本数并进 n，
    # 等于让一个"不参与判决"的场景去限制判决强度，与"哨兵不得影响判决"概念冲突（今日冷/热样本
    # 数恒相等，故这一步是**冗余、不改结果**；但语义上必须分离，否则将来冷/热样本数一旦分叉，
    # 哨兵就会悄悄削判定强度）。
    decision_counts: Dict[str, int] = {
        scenario: counts[scenario] for scenario in CONDITION_TWO_SCENARIOS if scenario in counts
    }
    p95_n = min(decision_counts.values()) if decision_counts else None
    _print_number("p95_n", None if p95_n is None else float(p95_n), 0)
    print(f"p95_note={_p95_note(p95_n, decision_counts)}")
    print(f"scenario_scope_note={SCENARIO_SCOPE_NOTE}")
    print("frontend_pct=unmeasured")
    print("frontend_note=本机无浏览器自动化基线；需用 Chrome DevTools Performance 手工录制卡盒滚动")
    rss_mb, rss_note = _rss_mb()
    _print_number("rss_mb", rss_mb, 2)
    print(f"rss_note={rss_note}")
    print("android=unmeasured")
    print("android_note=本机无 Android SDK/模拟器/Chaquopy 运行时，真机首启与 RSS 不可测")
    print(f"target_cold_start_s={TARGET_COLD_START_S:.1f}")
    print(f"target_long_read_cold_s={TARGET_LONG_READ_COLD_S:.1f}")
    print(f"target_cards_list_s={TARGET_CARDS_LIST_S:.1f}")
    print(f"target_warm_read_s={TARGET_WARM_READ_S:.1f}")
    print(f"target_source={TARGET_SOURCE}")
    print("target_status=confirmed")
    print(f"target_status_note={TARGET_STATUS_NOTE}")
    # 条件② 的判定集与哨兵角色：显式输出，供门禁断言"判定集恰 3 场景、warm_read 不参与"。
    print(f"condition_two_scenarios={','.join(CONDITION_TWO_SCENARIOS)}")
    print(f"warm_read_role={SENTINEL_ROLE}")
    print(f"warm_read_sentinel_note={SENTINEL_NOTE}")
    # 余量 = 实测 p95 ÷ (2×目标)：让"目标"与"余量"绑定出现，防止被拆开搬运。
    for scenario in ("cards_list", "long_read_cold", "warm_read", "cold_start"):
        value = p95_s[scenario]
        # 6 位小数：热读的余量只有 1e-5 量级（微秒命中 vs 0.2s 门限），位数少了会打成
        # 0.00x，读起来像"没测到"而不是"低四个数量级"。
        _print_number(
            f"headroom_to_2x_target_{scenario}",
            None if value is None else value / TWO_X_TARGET_S[scenario],
            6,
            "x",
        )
        # 哨兵场景的余量必须带角色标注：否则读者会把"热读余量极低"误读成"缓存没问题 ⇒ 不用优化"。
        if scenario in SENTINEL_SCENARIOS:
            print(f"headroom_to_2x_target_{scenario}_role={SENTINEL_ROLE}")
    print(
        "headroom_note=余量=实测 p95 ÷ (2×目标)：<1 表示尚未超过门限、≥1 表示条件②成立；"
        "与 target_status=confirmed 绑定阅读（目标值已拍板但性质为价值判断，目标一变余量即变）；"
        f"其中 headroom_to_2x_target_{SENTINEL_SCENARIOS[0]} 属缓存哨兵、不参与条件②"
    )
    print(f"verdict={_verdict(weighted_python_pct, p95_s, p95_n)}")
    return 0 if all(result.error is None for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
