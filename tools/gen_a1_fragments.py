# -*- coding: utf-8 -*-
"""ADR-0015 T2 生成器：A1 内容 → FRAGMENTS 单源 + membership side-car。

读取旧 ``A1_WORKBENCH_SEED`` / ``A1_WORKBENCH_CUSTOM`` / ``GOETHE_A1_VOCAB``，
写出：

- ``delector/data/a1_fragments.py`` —— 内容单源（5 元组分片 + 富字段分片）
- ``delector/data/a1_sidecar.py`` —— 身份/成员/展示层（id·letter·topic·custom22）

幂等：输入不变则输出字节稳定。**不**改 HTML；``tools/build_workbench_seed.py``
在 T5 改为从投影生成。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from delector.data.a1_dict import GOETHE_A1_VOCAB  # noqa: E402
from delector.data.a1_sidecar import A1_WORKBENCH_ID_ALIASES  # noqa: E402
from delector.data.a1_workbench_dict import (  # noqa: E402
    A1_WORKBENCH_CORE_IDS,
    A1_WORKBENCH_CUSTOM,
    A1_WORKBENCH_SEED,
)
from delector.data.lexicon_merge import lemma_key  # noqa: E402


def _repr(obj: Any) -> str:
    return repr(obj)


def build() -> Tuple[str, str]:
    wb_rich: Dict[str, Dict[str, Any]] = {}
    wb_five: Dict[str, Tuple[Any, ...]] = {}
    wb_membership: List[Dict[str, Any]] = []

    for w in A1_WORKBENCH_SEED:
        lemma = lemma_key(w["hw"])
        ex = list(w.get("ex") or [])
        first = ex[0] if ex else {}
        examples = [{"de": e.get("de") or "", "zh": e.get("zh") or ""} for e in ex]
        # lemma 键 RICH：同形异义（bitte/essen/leben/sie）只登记**首次**，供考纲 IPA 连接；
        # 工作台逐 id 内容以 membership 为唯一真相（FSRS 行不可被 lemma 合并抹平）。
        if lemma not in wb_rich:
            wb_rich[lemma] = {
                "ipa": w.get("ipa") or "",
                "example_de": first.get("de") or "",
                "example_zh": first.get("zh") or "",
                "examples": examples,
                "topic": "",
            }
        if lemma not in wb_five:
            wb_five[lemma] = ("A1", "", None, "", w.get("gloss") or "")
        wb_membership.append(
            {
                "id": w["id"],
                "lemma": lemma,
                "hw": w["hw"],
                "pos": w.get("pos") or "",
                "gloss": w.get("gloss") or "",
                "ipa": w.get("ipa") or "",
                "ex": examples,
                "letter": w.get("letter") or "",
                "page": w.get("page") if w.get("page") is not None else 0,
                "core": w["id"] in A1_WORKBENCH_CORE_IDS,
            }
        )

    custom_rows: List[Dict[str, Any]] = []
    for w in A1_WORKBENCH_CUSTOM:
        lemma = lemma_key(w["hw"])
        ex = list(w.get("ex") or [])
        first = ex[0] if ex else {}
        examples = [{"de": e.get("de") or "", "zh": e.get("zh") or ""} for e in ex]
        if lemma not in wb_rich:
            wb_rich[lemma] = {
                "ipa": w.get("ipa") or "",
                "example_de": first.get("de") or "",
                "example_zh": first.get("zh") or "",
                "examples": examples,
                "topic": "",
            }
        custom_rows.append(
            {
                "id": w["id"],
                "lemma": lemma,
                "hw": w["hw"],
                "pos": w.get("pos") or "",
                "gloss": w.get("gloss") or "",
                "ipa": w.get("ipa") or "",
                "ex": examples,
                "letter": w.get("letter") or "",
                "page": w.get("page") if w.get("page") is not None else 0,
                "tags": list(w.get("tags") or []),
                "custom": True,
                "up": w.get("up"),
            }
        )

    goe_rich: Dict[str, Dict[str, Any]] = {}
    goe_five: Dict[str, Tuple[Any, ...]] = {}
    goe_membership: List[str] = []
    goe_topics: Dict[str, str] = {}
    goe_display: Dict[str, Dict[str, Any]] = {}

    for lemma_raw, entry in GOETHE_A1_VOCAB.items():
        lemma = lemma_key(lemma_raw or entry.get("lemma") or "")
        goe_membership.append(lemma)
        goe_topics[lemma] = entry.get("topic") or ""
        ex_de = entry.get("example_de") or ""
        ex_zh = entry.get("example_zh") or ""
        goe_rich[lemma] = {
            "ipa": "",
            "example_de": ex_de,
            "example_zh": ex_zh,
            "examples": [{"de": ex_de, "zh": ex_zh}] if (ex_de or ex_zh) else [],
            "topic": entry.get("topic") or "",
        }
        gender = entry.get("gender")
        plural = entry.get("plural") or ""
        if gender in ("", "None"):
            gender = None
        # pos/plural 展示层：GOETHE 复数是完整形，不进 5 元组后缀位（ADR-0015）。
        goe_five[lemma] = ("A1", "", gender, "", entry.get("definition_zh") or "")
        goe_display[lemma] = {
            "word": entry.get("word") or "",
            "pos": entry.get("pos") or "",
            "gender": gender,
            "plural": plural,
            "definition_zh": entry.get("definition_zh") or "",
            "example_de": ex_de,
            "example_zh": ex_zh,
            "topic": entry.get("topic") or "",
            "lemma": entry.get("lemma") or lemma,
        }

    core_ids = sorted(A1_WORKBENCH_CORE_IDS)
    aliases = dict(A1_WORKBENCH_ID_ALIASES)

    fragments = f'''# -*- coding: utf-8 -*-
"""A1 内容 FRAGMENTS 单源（ADR-0015 T2，由 tools/gen_a1_fragments.py 生成）。

**勿手改内容字典**——改上游 seed/GOETHE 后重跑生成器。
展示层（hw / pos 标签 / letter / topic 序）在 ``a1_sidecar``，不进本模块。
"""

from typing import Any, Dict, Tuple

# 工作台 A1 富字段（人工 IPA + 多对例句）。键 = lemma_key。
WORKBENCH_A1_RICH: Dict[str, Dict[str, Any]] = {_repr(wb_rich)}

# 考纲 A1 富字段（例句 + topic 回填）。ipa 留空由 workbench-a1 / rich 补。
GOETHE_A1_RICH: Dict[str, Dict[str, Any]] = {_repr(goe_rich)}

# 5 元组分片：workbench-a1 主要贡献 def_zh（gloss）；goethe-a1 贡献 gender/plural/def_zh。
# pos 刻意留空串（view-owned，不进共享优先级争用）。
WORKBENCH_A1_FIVE: Dict[str, Tuple[Any, ...]] = {_repr(wb_five)}
GOETHE_A1_FIVE: Dict[str, Tuple[Any, ...]] = {_repr(goe_five)}
'''

    sidecar = f'''# -*- coding: utf-8 -*-
"""A1 身份 / 成员 / 展示层 side-car（ADR-0015 T2，由 tools/gen_a1_fragments.py 生成）。

不可从主干派生：FSRS id、letter 原值、成员集合、GOETHE topic 序、custom 22。
**勿手改**——改上游后重跑生成器。
"""

from typing import Any, Dict, List, Set

# 工作台成员：id -> 展示层 + lemma（FSRS 键空间，id/letter 逐字不变）。
WORKBENCH_MEMBERSHIP: List[Dict[str, Any]] = {_repr(wb_membership)}

# 考纲成员（有序 lemma）与 topic 映射。
GOETHE_MEMBERSHIP: List[str] = {_repr(goe_membership)}
GOETHE_TOPICS: Dict[str, str] = {_repr(goe_topics)}

# 考纲展示层（word / pos 标签等），投影 /api/a1/vocab 用。
GOETHE_DISPLAY: Dict[str, Dict[str, Any]] = {_repr(goe_display)}

# custom 22 全量条目（官方 A1 不含；scope=core 的 core-* ）。
CUSTOM_22: List[Dict[str, Any]] = {_repr(custom_rows)}

# 213 核心 id + 2 条历史 id 别名（语义不变，ADR-0014 修正点 ④）。
A1_WORKBENCH_CORE_IDS: Set[str] = set({_repr(core_ids)})
A1_WORKBENCH_ID_ALIASES: Dict[str, str] = {_repr(aliases)}
'''
    return fragments, sidecar


def main() -> int:
    fragments, sidecar = build()
    (ROOT / "delector" / "data" / "a1_fragments.py").write_text(fragments, encoding="utf-8")
    (ROOT / "delector" / "data" / "a1_sidecar.py").write_text(sidecar, encoding="utf-8")
    print("wrote a1_fragments.py + a1_sidecar.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
