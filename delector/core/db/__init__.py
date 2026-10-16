# -*- coding: utf-8 -*-
r"""`delector/core/database.py` 按职责切分后的子包（database-split）。

切片（每片一个模块，随切分进度增补）：
- `backup` ← 备份 / 还原 / 白名单（含两份 pending 暂存槽；模块级状态随迁）

纪律：
- 切片之间与对外一律**绝对导入**（`from delector.core.db.backup import X`）。
- 本 `__init__` 刻意**不 import 任何切片**：保持轻量、避免导入副作用与导入环；
  消费方仍可走 `delector.core.database` 的 façade，或直接走子模块路径。
"""
