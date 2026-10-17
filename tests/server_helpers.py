# -*- coding: utf-8 -*-
"""tests/ 侧共享 helper：跨域共用的模块级常量与纯函数（C6 Task 1 提取）。

为什么要这一层
--------------
`test_server.py` 正按被测面切分为多个 `tests/test_server_<domain>.py`。符号若只靠
「同文件隐式可见性」被多个域共用，切分后即断裂；本模块把这类**跨域**项显式化，
各域文件按名 import，不再依赖隐式可见性。

纪律
----
- 只收跨域共用项：单一域内使用的 helper 留在各测试文件里、随其域搬迁。
- 测试文件 MUST 显式 `from server_helpers import ...`；禁止 import * / re-export 桥。
- 本模块不得 import 任何 `test_*.py`（依赖方向：测试文件 → 本模块 → 被测代码）。
"""

import os
from typing import Any, Dict

from delector.core.database import db_conn

# 仓库根：凡读仓库资源（server.py / static / tools / android / .github / .githooks /
# nlp.py / package_windows.py）一律经 ROOT。别再写 os.path.dirname(__file__) 相对测试
# 文件推 —— tests/ 比仓库根深一层，那会指到 tests/。
ROOT = os.path.dirname(os.path.dirname(__file__))


def _insert_vocab_card(**over: object) -> int:
    """直插一行 vocab_cards（绕过建卡端点，以便精确摆出 fsrs_*/repetition_count 组合）。

    最小必填列：word / lemma / definition_zh / sentence_context。
    """
    row: Dict[str, Any] = {
        "word": "Haus",
        "lemma": "Haus",
        "definition_zh": "房子",
        "sentence_context": "Das Haus ist alt.",
    }
    row.update(over)
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards "
            "(word, lemma, definition_zh, sentence_context, fsrs_s, repetition_count, mastered, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["word"],
                row["lemma"],
                row["definition_zh"],
                row["sentence_context"],
                row.get("fsrs_s"),
                row.get("repetition_count", 0),
                row.get("mastered", 0),
                row.get("due_date"),
            ),
        )
        return int(cur.lastrowid or 0)
