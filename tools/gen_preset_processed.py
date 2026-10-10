#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""构建期生成器：为预置文章预生成 spaCy 口径的 processed_json（子计划 2A）。

为什么在构建期算（消灭的缺陷）
==============================
预置文章是**随代码发布的固定文本**。原实现把「算准」推迟到运行时：列表预览走纯 Python 口径、
首次打开被惰性迁移升级成 spaCy 口径 ⇒ 用户看到「列表 A2 → 点进去 A1」的难度跳变。谁固定，
就在哪算 —— 构建期用 spaCy 口径算一次、落成数据文件，运行时只读不算（不加载模型）。

口径一致性（生成器 ↔ 服务端）
==============================
- **共用同一个 `process_german_text`**：生成器调用的就是服务端落库用的那个函数，不存在「两套实现
  各算一份」导致口径漂移的可能；
- **共用 `PROCESSED_JSON_VERSION`**：条目里的 version 取自 processor 的唯一真相源；运行时按它
  判「命中」、版本不符即回退（见 delector/core/database.py）；
- **共用文本哈希**：生成器与运行时都调 `database.preset_text_hash`，保证「命中」判据同源。

幂等
====
同输入重复生成结果一致（除 `generated_at` 时间字段）：正文哈希索引 + `sort_keys=True` 落盘。
守卫 tests/test_preset_processed_data.py 按哈希逐篇断言覆盖 + 无多余条目。

隔离纪律
========
`database.py` 在**导入期**就按 `DELECTOR_DATA_DIR` 建 `.cache/audio`，故先把三个数据路径钉进
临时目录再导入 —— **绝不**读用户 `.env`、**绝不**碰真实学习库。

用法
====
::

    export PYTHONIOENCODING=utf-8
    python tools/gen_preset_processed.py

输出仅用 ASCII 标记（GBK 控制台安全）。spaCy 缺失时**响亮失败**，不落一份错口径的数据。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 数据文件落点：MUST 与运行时 database.preset_processed_data_path() 指同一处。
_OUTPUT_PATH = os.path.join(_REPO_ROOT, "delector", "data", "preset_processed.json")


def _pin_isolated_env(tmpdir: str) -> None:
    """把三个数据路径钉进临时目录，再导入 delector（导入期建目录 / 可能打开库）。"""
    os.environ["DELECTOR_DATA_DIR"] = tmpdir
    os.environ["DATABASE_PATH"] = os.path.join(tmpdir, "gen.db")
    os.environ["PROGRESS_DB_PATH"] = os.path.join(tmpdir, "gen_progress.db")


def _resolved_model(processor: Any) -> str:
    """从 processor 的引擎详情里反解**实际生效**的德语模型包名（拿不到回空串）。"""
    detail = str(getattr(processor, "NLP_ENGINE_DETAIL", ""))
    for candidate in processor.SPACY_MODEL_CANDIDATES:
        if candidate in detail:
            return str(candidate)
    return ""


def _build_payload() -> Dict[str, Any]:
    """跑 spaCy 口径组装 payload；spaCy 不可用时**响亮失败**（宁可不生成，也不落错口径）。"""
    from delector.core.database import PRESET_ARTICLES, PRESET_PROCESSED_SCHEMA, preset_text_hash
    from delector.nlp_engine import processor
    from delector.nlp_engine.processor import PROCESSED_JSON_VERSION, process_german_text

    if processor.nlp is None:
        # 纯 Python 兜底（spaCy 缺失 / Android）会产出**非 spaCy 口径**的数据，违背本任务目的：
        # 落一份错口径数据后运行时「命中」反而把错的用上。故在此硬失败，不写文件。
        raise SystemExit(
            "[gen_preset_processed] spaCy 不可用（processor.nlp is None）：拒绝生成纯 Python 口径数据"
        )

    entries: Dict[str, Any] = {}
    for art in PRESET_ARTICLES:
        text = art["text"]
        # 与**服务端落库**共用同一个函数；模型缺失时它会硬失败（不静默降级）。
        processed = process_german_text(text)
        text_hash = preset_text_hash(text)
        entries[text_hash] = {
            "text_hash": text_hash,
            "version": processed.get("version"),
            "processed": processed,
        }
    return {
        "schema": PRESET_PROCESSED_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "processed_json_version": PROCESSED_JSON_VERSION,
        "model": _resolved_model(processor),
        # 生成时的**运行时签名**（含 spaCy 版本 + 模型名）：守卫据此判「本机环境与生成时是否同源」，
        # 同源才做逐字口径比对 —— `requirements` 是 `spacy>=3.8.16`（上不封顶），跨版本比对会抖动。
        "runtime": str(getattr(processor, "NLP_ENGINE_DETAIL", "")).strip(),
        "article_count": len(PRESET_ARTICLES),
        "entries": entries,
    }


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="delector_gen_preset_")
    _pin_isolated_env(tmpdir)
    payload = _build_payload()
    os.makedirs(os.path.dirname(_OUTPUT_PATH), exist_ok=True)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as handle:
        # sort_keys 保证同输入同输出（除 generated_at）；正文哈希索引 + 该键序使重复生成幂等。
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    size = os.path.getsize(_OUTPUT_PATH)
    print("=== gen_preset_processed ===")
    print(f"output={_OUTPUT_PATH}")
    print(f"bytes={size}")
    print(f"entries={len(payload['entries'])}")
    print(f"processed_json_version={payload['processed_json_version']}")
    print(f"model={payload['model']}")
    print(f"schema={payload['schema']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
