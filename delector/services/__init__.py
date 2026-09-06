# -*- coding: utf-8 -*-
"""业务逻辑服务层（ADR-0008 Phase 1 Task 5）。

收编原 delector/ 包根的 4 个服务模块：
- `writing`    ← writing_rules.py（德语写作本地规则引擎）
- `essay_diff` ← essay_diff.py（句子级 diff / merge 引擎）
- `exam_catalog` ← exam_catalog.py（等级→模块导航目录）
- `tts`        ← edge_tts_mini.py（标准库版 Edge TTS 客户端）

`edge_tts_mini` 在 Phase 1 Task 5 迁到 `delector.services.tts`（原名保留为模块内的
语义别名概念）；`routes/main.py` 的 `generate_edge_tts_audio` 用
`from delector.services import tts as edge_tts_mini` 延迟导入，`test_server` 的降级链
monkeypatch 打在 `sys.modules["delector.services.tts"]` + `delector.services.tts` 属性上。

纪律：
- 模块内一律 `from delector.services.X import Y` 绝对导入，不用相对导入。
- 本文件显式 `__all__`，不外泄子模块内部 `_` 符号。
- 消费方尽量直连子模块（如 `from delector.services.writing import analyze_essay_text`），
  此处的扁平 re-export 仅作便利入口。
"""
from delector.services import essay_diff, exam_catalog, tts, writing
from delector.services.essay_diff import (
    diff_sentences,
    join_sentences,
    merge_sentences,
    split_sentences,
)
from delector.services.exam_catalog import EXAM_CATALOG, get_catalog
from delector.services.tts import synthesize
from delector.services.writing import (
    analyze_a1_email,
    analyze_essay_text,
    check_a1_formular_answer,
    decline_determiner,
    detect_determiner_noun_agreement,
    detect_preposition_case,
)

__all__ = [
    "essay_diff",
    "exam_catalog",
    "tts",
    "writing",
    "diff_sentences",
    "join_sentences",
    "merge_sentences",
    "split_sentences",
    "EXAM_CATALOG",
    "get_catalog",
    "synthesize",
    "analyze_a1_email",
    "analyze_essay_text",
    "check_a1_formular_answer",
    "decline_determiner",
    "detect_determiner_noun_agreement",
    "detect_preposition_case",
]
