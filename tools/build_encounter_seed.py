# -*- coding: utf-8 -*-
"""离线产包脚本：从仓库既有 OFFLINE 语料生成 encounter-pack/v1 预置包模块。

用途
----
把 `delector/data/corpus_dict.py` 的 `OFFICIAL_CORPUS`（A1–B2 真实分级德语短文）
编译成 `encounter-pack/v1` 卡包列表，输出为 **纯数据 Python 模块**
`delector/data/encounter_seed_dict.py`，供 T4 的幂等导入（按 pack_id 去重）消费，
让「遇见区」离线即有内容，不依赖运行时 LLM 或网络。

口径纪律（与规划阶段已定设计一致，勿擅改）
--------------------------------------------
- 素材来源 = 仓库既有 `OFFICIAL_CORPUS` 的 `content`（真实分级短文）；
  **不新写文案、不调 LLM、不抓取外部内容**。
- 分词 = 既有 `process_german_text`（spaCy，离线；无 spacy 时自动走纯 Python 降级）。
- 分析字段 = 离线纯函数 `delector.tools.vocab_stats.run`（考纲 A1∪A2 lemma 集，
  无 DB 无网络），即 job#1 gloss 前一步的**同一实现**；其 `unknown_ranked`
  映射为 pack.analysis 的 `unknown_lemmas`。
- `estimated_cefr` 取语料自带 `cefr`（考纲权威分级），**不用**启发式 `level_hint` 覆盖。
- `glosses` 留空数组：阅读时释义走 `/api/lookup/vocab` 本地词典，UI 不消费 pack.glosses
  （`validate_pack` 亦不强制 glosses 非空）。
- `pack_id` 固定 `seed-corpus-<corpus_id>`，供下游按 pack_id 幂等去重。

确定性声明
----------
同一输入 + 同一 levels 必须产出 **字节一致** 的结果：语料按 pack_id 排序输出、
固定 `json.dumps(indent=4, ensure_ascii=False)`、末尾统一 LF、无随机化、无
运行时时间戳漂移（created_at 由 CLI 注入，默认取当天日期，仅写进头部注释）。

生成命令
--------
    export PYTHONIOENCODING=utf-8
    python tools/build_encounter_seed.py

可选参数：
    --out PATH        产物路径（默认 delector/data/encounter_seed_dict.py）
    --levels A1,A2    参与产包的语料分级（默认 A1,A2）
    --created-at DATE 产物头部注释里的日期（ISO 字符串，默认今天）

禁止手工改 `delector/data/encounter_seed_dict.py` 的内容 —— 要改就重跑本脚本。
"""
import argparse
import asyncio
import datetime
import json
import os
import sys

# 允许从仓库根直接 `python tools/build_encounter_seed.py` 运行：把仓库根加入 sys.path。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# encounter-pack/v1 契约版本（与 delector/routes/encounter.py 的 CARD_PACK_SCHEMA 同值）。
_PACK_SCHEMA = "encounter-pack/v1"
# 默认产物路径与默认分级。
_DEFAULT_OUT = os.path.join(_REPO_ROOT, "delector", "data", "encounter_seed_dict.py")
_DEFAULT_LEVELS = "A1,A2"

# 产物头部注释模板（时间戳/命令由 CLI 注入；中文不转义）。
_HEADER_TEMPLATE = '''# -*- coding: utf-8 -*-
"""预置遇见区卡包（encounter-pack/v1）—— 由离线脚本生成，请勿手工编辑。

来源（Source of Truth）
    delector/data/corpus_dict.py 的 OFFICIAL_CORPUS（A1–B2 真实分级德语短文）。

生成命令（Reproducible Command）
    export PYTHONIOENCODING=utf-8
    python tools/build_encounter_seed.py --levels {levels} --created-at {created_at}

生成日期（Created At）
    {created_at}

分级依据（Level Basis）
    estimated_cefr 直接取语料自带 cefr 字段（考纲权威分级）；
    不使用 vocab_stats 的启发式 level_hint 覆盖。

分析字段（Analysis）
    每包 analysis 由离线纯函数 delector.tools.vocab_stats.run 生成
    （考纲 A1∪A2 lemma 覆盖统计，无 DB/网络）；未知词频排名映射为 unknown_lemmas。

免责（Determinism & Immutability）
    本模块为纯数据：仅导出 PRESET_ENCOUNTER_PACKS，导入期零 spaCy、零网络、零副作用
    （项目红线 9）。内容由脚本确定性生成，同输入字节一致；
    **禁止手工改内容，改则重跑 tools/build_encounter_seed.py**。
"""
from typing import Any

# 预置卡包列表（encounter-pack/v1）。列表顺序 = pack_id 升序，保证确定性。
PRESET_ENCOUNTER_PACKS: list[dict[str, Any]] = '''


def _parse_levels(raw: str) -> list:
    """把 "A1,A2" 解析为去空白、去重、保序的等级列表。"""
    out = []
    for part in (raw or "").split(","):
        lv = part.strip().upper()
        if lv and lv not in out:
            out.append(lv)
    return out


def _collect_tokens(parsed: dict) -> list:
    """从 process_german_text 的返回结构里抽平所有句子的 tokens（保留 text/lemma/pos）。

    标点 token（is_punct）/空白 token（is_space）保留在 payload 里但词表统计只按
    lemma 计；这里与 vocab_stats 契约一致，直接透传 token dict。
    """
    tokens = []
    for sent in parsed.get("sentences", []):
        tokens.extend(sent.get("tokens", []))
    return tokens


def build_packs(levels: list) -> list:
    """按 levels 筛选 OFFICIAL_CORPUS 并逐篇产 encounter-pack/v1 dict 列表。

    返回列表按 pack_id 升序（确定性）；每包结构见 validate_pack 契约：
    必需顶层 {schema, pack_id, article{title, raw_text}}，附带 estimated_cefr/analysis/glosses。
    """
    from delector.data.corpus_dict import OFFICIAL_CORPUS
    from delector.nlp_engine import process_german_text
    from delector.tools import vocab_stats

    level_set = set(levels)
    packs = []
    for item in OFFICIAL_CORPUS:
        corpus_id = item["id"]
        cefr = item["cefr"]
        if cefr not in level_set:
            continue

        content = item["content"]
        parsed = process_german_text(content)
        tokens = _collect_tokens(parsed)

        # 离线纯函数分析（与 job#1 gloss 同源）。async def run -> asyncio.run。
        stats = asyncio.run(vocab_stats.run({"tokens": tokens}))

        pack = {
            "schema": _PACK_SCHEMA,
            "pack_id": f"seed-corpus-{corpus_id}",
            "estimated_cefr": cefr,
            "analysis": {
                "tokens_total": stats["tokens_total"],
                "known_count": stats["known_count"],
                "known_rate": stats["known_rate"],
                "unknown_lemmas": stats["unknown_ranked"],
                "level_hint": stats["level_hint"],
            },
            "glosses": [],
            "article": {
                "title": item["title"],
                "raw_text": content,
            },
        }
        packs.append(pack)

    # 确定性：按 pack_id 升序。
    packs.sort(key=lambda p: p["pack_id"])
    return packs


def render_module(packs: list, levels: list, created_at: str) -> str:
    """渲染完整 Python 模块源码字符串（含头部注释 + 纯字面量数据）。

    使用 json.dumps(indent=4, ensure_ascii=False) —— 其输出（对象/数组/字符串/数字/
    true/false/null）是合法 Python 字面量子集；中文不转义。末尾统一 LF。
    """
    body = json.dumps(packs, indent=4, ensure_ascii=False)
    header = _HEADER_TEMPLATE.format(levels=",".join(levels), created_at=created_at)
    return header + body + "\n"


def _require_spacy_model() -> None:
    """离线工具前置检查：spaCy 模型不可用时给出明确报错（允许失败但要清晰）。

    走 process_german_text 的实际引擎探测：若退化为纯 Python 路径，正文会带
    NLP_ENGINE 的描述；本脚本只做「显式警告」，不静默降级（产出质量需可知）。
    """
    try:
        from delector.nlp_engine import processor
    except Exception as exc:  # pragma: no cover - 环境相关
        raise SystemExit(
            f"[build_encounter_seed] 无法导入 delector.nlp_engine: {exc!r}\n"
            "请确认在仓库根运行，且已安装依赖（spaCy + de_core_news_* 德语模型）。"
        )
    if processor.nlp is None:
        raise SystemExit(
            "[build_encounter_seed] spaCy 德语模型不可用，已退化为纯 Python 路径：\n"
            f"  {processor.NLP_ENGINE_DETAIL}\n"
            "离线产包需要 spaCy 模型（de_core_news_md / de_core_news_sm）。\n"
            "安装示例：python -m spacy download de_core_news_sm"
        )
    # 打印实际生效引擎，便于复现时确认。
    print(f"[build_encounter_seed] NLP 引擎: {processor.NLP_ENGINE} — {processor.NLP_ENGINE_DETAIL}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 OFFICIAL_CORPUS 离线生成 encounter-pack/v1 预置包模块。"
    )
    parser.add_argument("--out", default=_DEFAULT_OUT, help="产物路径")
    parser.add_argument("--levels", default=_DEFAULT_LEVELS, help="参与分级（逗号分隔，默认 A1,A2）")
    parser.add_argument(
        "--created-at",
        default=datetime.date.today().isoformat(),
        help="产物头部注释里的日期（ISO 字符串，默认今天）",
    )
    args = parser.parse_args()

    levels = _parse_levels(args.levels)
    if not levels:
        raise SystemExit("[build_encounter_seed] --levels 解析为空，请传入如 A1,A2")

    _require_spacy_model()

    packs = build_packs(levels)

    # levels 分布统计（打印）。
    dist = {}
    for p in packs:
        dist[p["estimated_cefr"]] = dist.get(p["estimated_cefr"], 0) + 1
    dist_str = ", ".join(f"{lv}:{dist[lv]}" for lv in sorted(dist))
    print(f"[build_encounter_seed] 产出包数: {len(packs)}; levels 分布: {dist_str}")

    module_src = render_module(packs, levels, args.created_at)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # 固定 UTF-8 + LF 行尾写入，保证跨平台字节一致。
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(module_src)
    print(f"[build_encounter_seed] 已写出: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
