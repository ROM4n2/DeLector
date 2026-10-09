# -*- coding: utf-8 -*-
"""基准计时的统计口径：中位数与 p95 **共用同一批样本**（Task 5b）。

为什么单独一个模块
------------------
三个基准（卡盒 / 长文 / 冷启动）都要输出 p95，且**算法必须三处完全一致**。各写一份
等于给"口径漂移"留三个入口：将来有人只改一处，三个场景的 p95 就不再可比，而数字看
上去仍然是"各自实测"的。故抽到这一处，三个基准都从这里取。

分位算法与它的**已知偏差**（务必连同数字一起读，不许只搬数字）
----------------------------------------------------------------
`statistics.quantiles(sorted(samples), n=100, method="inclusive")[94]`。

- 为什么取下标 94：`n=100` 返回 99 个切点，第 94 个（0-based）即 p95。
- 为什么 `inclusive`：`exclusive` 会把切点外推到样本范围之外（小样本下能算出比最小值
  还小的分位数），只有 `inclusive` 保证分位落在 ``[min, max]`` 内。
- **n=5 时该值 ≈ 最大值**：切点位置 = 94×(5−1)/99 = 3.80，已插值到升序第 4、第 5 个
  样本之间。但它**仍然系统性低估真尾部**：P(max₅ < 真 p95) = 0.95⁵ ≈ 77%，即约 3/4
  的情况下"5 次采样里最大的那个"都够不着真正的 p95。

  ⇒ 结论纪律（写进本模块是因为读数字的人不看各基准的 docstring）：
  **n < 20 时 p95 未超门限只能写"仅可否证（未能确证不成立）"，不得写"不成立"**；
  要写强结论须先把样本量提到 n ≥ 20（各基准用 `BENCH_P95_ROUNDS` 提，不改代码）。

为什么强调"同批样本，不重新计时"
--------------------------------
p95 若另跑一轮计时，就不再是"与中位数同一次测量"的尾部 —— 中位数与 p95 会来自两个
不同的抖动过程，二者之差（尾部有多厚）失去意义。故三个基准一律先采样本，再从中同时
折叠出中位数与 p95。
"""

from __future__ import annotations

import statistics
from typing import Sequence


def p95_ms(samples: Sequence[float]) -> float:
    """对**已采集**的样本取 p95（毫秒）。不做任何重新计时。

    样本数 < 2 时 `statistics.quantiles` 会抛 `StatisticsError`，此处退回最大值：
    单点样本的分位无定义，报最大值比抛异常更贴近"尾部最坏情况"，也避免基准在极小
    样本档直接崩掉。
    """
    if not samples:
        return 0.0
    if len(samples) < 2:
        return float(max(samples))
    return float(statistics.quantiles(sorted(samples), n=100, method="inclusive")[94])


def median_ms(samples: Sequence[float]) -> float:
    """对同一批样本取中位数（毫秒）——与 `p95_ms` 同源，保证两者可比。"""
    return float(statistics.median(samples))


def format_samples(samples: Sequence[float]) -> str:
    """把样本打印成逗号分隔串：让下游（含 ADR 回填）能**自己重算**分位。

    只给 p95 数字而不给样本，"p95 是不是拿中位数冒充的"就无从复核 —— 门禁正是靠
    重算这一串来钉死同批样本这条纪律。
    """
    return ",".join(f"{value:.6f}" for value in samples)
