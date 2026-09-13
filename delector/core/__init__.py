# -*- coding: utf-8 -*-
"""基础设施层（ADR-0008 Phase 1 Task 6）。

收编原 delector/ 包根的重量级基础设施模块：
- `database` ← database.py（SQLite 操作 + 配置存储 + 音频缓存 + 备份还原）
- `security` ← security.py（SSRF 判定 + 安全抓取 + RSS 解析）
- `utils`    ← utils.py（平台探测 + 附件响应头，零包内依赖）

纪律：
- `database` / `security` 较重（database 拉 spacy 链路），故本 __init__ 只 re-export
  轻量的 `utils` 符号；`database` / `security` 请走子模块路径
  `from delector.core.database import X`，避免无关导入触发 spacy 加载。
- 消费方一律 `from delector.core.X import Y` 绝对导入，不用相对导入。
- 模块内也用绝对导入（见 routes/main.py docstring 的踩坑记录）。
"""

from delector.core.utils import (
    _NO_STORE_HEADERS,
    _attachment_headers,
    is_android,
)

__all__ = ["_NO_STORE_HEADERS", "_attachment_headers", "is_android"]
