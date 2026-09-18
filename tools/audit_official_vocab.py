# -*- coding: utf-8 -*-
"""官方词表来源对账工具（ADR-0012 来源可审计 / Task R7）。

用途
----
每次更换「官方歌德词表」分片时，用本工具一键对账三片来源
（``ai`` / ``manual`` / ``official``）的一致性，把「换词表引入的差异」变成
**可复现、可审计**的结构化报告，而不是靠肉眼 diff 两个巨型字典。

对账对象（真实三片）
    ``delector.core.lexicon.FRAGMENTS``
        ``{"ai": CORE_VOCAB_EXT, "manual": CORE_VOCAB_MANUAL, "official": OFFICIAL_VOCAB}``
    消费端统一走主干 ``delector.core.lexicon``（ADR-0012），本工具亦如此。

输出四类结果（见 :func:`audit`）
    - ``counts``          各来源条数；
    - ``pairwise``        两两来源的 ``intersection`` / ``only_a`` / ``only_b``（条数）；
    - ``cefr_conflicts``  同 lemma 在不同来源 cefr 不一致的明细（按条数汇总 + 可截断明细）；
    - ``noise_candidates``疑似噪声 lemma（非德语字符集 / 英语词黑名单），**只报告不删**。

字段级优先级（``source_priority_note``，与 ``delector.data.lexicon_merge.FIELD_PRIORITY`` 一致）
    - ``cefr``：``official > manual > ai``（难度等级以官方考纲为权威）；
    - ``pos`` / ``gender`` / ``plural`` / ``def_zh``：``manual > official > ai``
      （富字段保留人工质量，官方仅补手编缺失处）。
    本工具**只对账不改数据**：真实合并始终走主干 ``merge_fragments``（单真值），
    本报告仅作审计参考。

用法
----
    export PYTHONIOENCODING=utf-8
    python tools/audit_official_vocab.py            # 人类可读摘要
    python tools/audit_official_vocab.py --json     # 机器可读 JSON（stdout）

约束
----
纯只读、零网络、零写盘：只读内存常量，绝不改写任何分片或存储（JSON 只打到 stdout）。
:func:`audit` 及其全部辅助函数均为**确定性纯函数**，同输入必得同输出
（内部对 lemma 排序，不依赖 set 哈希顺序）。
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

# 允许从仓库根直接 `python tools/audit_official_vocab.py` 运行：把仓库根加入 sys.path。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 5 元组字段顺序（与 delector.data.lexicon_merge.FIELD_ORDER / 存储 schema 一致）：
# (cefr, pos, gender, plural, def_zh)。cefr 位于下标 0。
_CEFR_INDEX = 0

# 合法德语 lemma 字符集：小写拉丁 + 变音 äöüß + 可分动词连字符。
# 实测三片 lemma 全部落在该集合内；将来出现集外字符即视为疑似噪声（只报告不删）。
_GERMAN_LEMMA_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzäöüß-")

# 小型英语词黑名单：明显是英语、非德语词条的 lemma（如 ai 片混入的 "dishwasher"）。
# 刻意保持极小、只放「铁定不是德语」的英语词，避免误伤 Computer/Handy 等德语借词。
_ENGLISH_NOISE_BLACKLIST = frozenset(
    {
        "dishwasher",
        "refrigerator",
        "vacuum",
        "laundry",
        "stove",
    }
)

# 字段级优先级说明（与 lexicon_merge.FIELD_PRIORITY 同源语义，仅作报告文字）。
_SOURCE_PRIORITY_NOTE = "cefr: official>manual>ai；富字段(pos/gender/plural/def_zh): manual>official>ai"

# 明细截断上限（报告只截断显示，count 始终是真实总数）。
_MAX_CEFR_DETAILS = 50
_MAX_NOISE_DETAILS = 100


def non_german_chars(lemma: str) -> Tuple[str, ...]:
    """返回 lemma 中不属于德语字符集的字符（保序、去重）。纯函数。"""
    extras: List[str] = []
    for ch in lemma:
        if ch not in _GERMAN_LEMMA_CHARS and ch not in extras:
            extras.append(ch)
    return tuple(extras)


def noise_reason(lemma: str) -> Optional[str]:
    """判定 lemma 是否疑似噪声，返回原因字符串；非噪声返回 ``None``（纯函数）。

    噪声启发式（**只报告不删**）：lemma 含德语字符集外字符，或命中英语词黑名单。
    """
    extras = non_german_chars(lemma)
    if extras:
        return "含非德语字符集外字符: " + "".join(extras)
    if lemma.lower() in _ENGLISH_NOISE_BLACKLIST:
        return "命中英语词黑名单"
    return None


def _pairwise(fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]], names: List[str]) -> Dict[str, Any]:
    """两两来源的 ``intersection`` / ``only_a`` / ``only_b``（条数）。纯函数。"""
    result: Dict[str, Any] = {}
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            keys_a = set(fragments[a])
            keys_b = set(fragments[b])
            result[f"{a}|{b}"] = {
                "sources": [a, b],
                "intersection": len(keys_a & keys_b),
                "only_a": len(keys_a - keys_b),
                "only_b": len(keys_b - keys_a),
            }
    return result


def _cefr_conflicts(fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]], names: List[str]) -> Dict[str, Any]:
    """同 lemma 在不同来源 cefr 不一致的明细（汇总条数 + 可截断明细）。纯函数。"""
    by_lemma: Dict[str, Dict[str, Any]] = {}
    for name in names:
        for lemma, row in fragments[name].items():
            by_lemma.setdefault(lemma, {})[name] = row[_CEFR_INDEX]
    details: List[Dict[str, Any]] = []
    for lemma in sorted(by_lemma):
        mapping = by_lemma[lemma]
        if len(set(mapping.values())) > 1:
            details.append({"lemma": lemma, "by_source": mapping})
    return {
        "count": len(details),
        "details": details[:_MAX_CEFR_DETAILS],
        "truncated": len(details) > _MAX_CEFR_DETAILS,
    }


def _noise_candidates(fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]], names: List[str]) -> Dict[str, Any]:
    """疑似噪声 lemma（每项附来源与原因；汇总条数 + 可截断明细）。纯函数。"""
    details: List[Dict[str, Any]] = []
    for name in names:
        for lemma in sorted(fragments[name]):
            reason = noise_reason(lemma)
            if reason is not None:
                details.append({"lemma": lemma, "source": name, "reason": reason})
    return {
        "count": len(details),
        "details": details[:_MAX_NOISE_DETAILS],
        "truncated": len(details) > _MAX_NOISE_DETAILS,
    }


def audit(fragments: Mapping[str, Mapping[str, Tuple[Any, ...]]]) -> Dict[str, Any]:
    """对账多来源分片，返回结构化结果（纯函数、零副作用、确定性）。

    ``fragments``：``{来源名: {lemma: 5 元组}}``（键序即来源顺序，用于 pairwise 命名）。
    返回值键：``counts`` / ``pairwise`` / ``cefr_conflicts`` / ``noise_candidates`` /
    ``source_priority_note``。
    """
    names = list(fragments.keys())
    return {
        "counts": {name: len(fragments[name]) for name in names},
        "pairwise": _pairwise(fragments, names),
        "cefr_conflicts": _cefr_conflicts(fragments, names),
        "noise_candidates": _noise_candidates(fragments, names),
        "source_priority_note": _SOURCE_PRIORITY_NOTE,
    }


def format_summary(report: Dict[str, Any], max_items: int = 10) -> str:
    """把 :func:`audit` 的结果渲染成人类可读摘要（纯函数）。"""
    lines: List[str] = []
    lines.append("=== 官方词表来源对账 (audit_official_vocab) ===")
    lines.append("")
    lines.append("[各来源条数]")
    counts = report["counts"]
    for name in counts:
        lines.append(f"  {name}: {counts[name]}")
    lines.append("")
    lines.append("[两两来源交集]")
    for key in report["pairwise"]:
        pw = report["pairwise"][key]
        a, b = pw["sources"]
        lines.append(
            f"  {a} ∩ {b}: intersection={pw['intersection']} "
            f"only_{a}={pw['only_a']} only_{b}={pw['only_b']}"
        )
    lines.append("")
    cc = report["cefr_conflicts"]
    suffix = "（明细已截断）" if cc["truncated"] else ""
    lines.append(f"[cefr 冲突] 条数={cc['count']}{suffix}")
    for d in cc["details"][:max_items]:
        lines.append(f"  {d['lemma']}: {d['by_source']}")
    lines.append("")
    nc = report["noise_candidates"]
    suffix = "（明细已截断）" if nc["truncated"] else ""
    lines.append(f"[噪声候选（只报告不删）] 条数={nc['count']}{suffix}")
    for d in nc["details"][:max_items]:
        lines.append(f"  {d['lemma']} ({d['source']}): {d['reason']}")
    lines.append("")
    lines.append(f"[字段级优先级] {report['source_priority_note']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI 入口：默认打印摘要，``--json`` 打印机器可读 JSON（只读、零网络、零写盘）。"""
    parser = argparse.ArgumentParser(
        prog="audit_official_vocab",
        description="对账官方词表三片来源（ai/manual/official）的一致性（只读、零网络、零写盘）。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 到 stdout（默认输出人类可读摘要）",
    )
    args = parser.parse_args(argv)

    # 惰性导入：只有真正运行时才加载分片（保持模块导入轻量，便于单测按路径加载纯函数）。
    from delector.core.lexicon import FRAGMENTS

    report = audit(FRAGMENTS)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
