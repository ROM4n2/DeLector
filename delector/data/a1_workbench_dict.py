# -*- coding: utf-8 -*-
"""A1 工作台 membership **投影入口**（ADR-0015 T2）。

内容/身份单源在 ``a1_sidecar``（id·letter·hw·ipa·ex）与 ``a1_fragments``（lemma 富字段）。
``A1_WORKBENCH_SEED`` / ``A1_WORKBENCH_CUSTOM`` 由 membership 逐 id 回放（FSRS 行不可被
lemma 合并抹平）。HTML 内联是构建产物，见 ``tools/build_workbench_seed.py``。
"""

from typing import Any, Dict, FrozenSet, List

from delector.data.a1_sidecar import (
    A1_WORKBENCH_CORE_IDS as _CORE_ID_SET,
)
from delector.data.a1_sidecar import (
    A1_WORKBENCH_ID_ALIASES,
    CUSTOM_22,
    WORKBENCH_MEMBERSHIP,
)


def _seed_row(m: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": m["id"],
        "hw": m["hw"],
        "pos": m.get("pos") or "",
        "gloss": m.get("gloss") or "",
        "ipa": m.get("ipa") or "",
        "ex": list(m.get("ex") or []),
        "letter": m.get("letter") or "",
        "page": m.get("page") if m.get("page") is not None else 0,
    }


def _custom_row(m: Dict[str, Any]) -> Dict[str, Any]:
    row = _seed_row(m)
    row["tags"] = list(m.get("tags") or [])
    row["custom"] = True
    row["up"] = m.get("up")
    return row


A1_WORKBENCH_SEED: List[Dict[str, Any]] = [_seed_row(m) for m in WORKBENCH_MEMBERSHIP]
A1_WORKBENCH_CUSTOM: List[Dict[str, Any]] = [_custom_row(m) for m in CUSTOM_22]
A1_WORKBENCH_CORE_IDS: FrozenSet[str] = frozenset(_CORE_ID_SET)
A1_WORKBENCH_ID_ALIASES: Dict[str, str] = A1_WORKBENCH_ID_ALIASES
