# -*- coding: utf-8 -*-
r"""`delector/core/database.py` 按职责切分后的子包（database-split）。

切片（每片一个模块，随切分进度增补）：
- `connection` ← 连接访问器 / 库文件·数据目录路径 / preflight 迁移闸 / 库级基础读写
  （进度事件、workbench 镜像、搭配已入卡、句法雷达统计）；`_INITIALIZED_PROGRESS_DBS`
  模块级去重集合随迁（Task 5 收口）。**最底层一片**：顶层只依赖标准库，不 import `database`
  也不 import 兄弟切片，故可被其它切片经 `database` 的 re-export 取用。
- `backup` ← 备份 / 还原 / 白名单（含两份 pending 暂存槽；模块级状态随迁）
- `settings` ← 设置持久化与鉴权（app_settings 读写、API 生效值、workbench 同步密钥）
- `schema` ← 建表 / 索引 / 内联列迁移（主库 + progress 库，含 A1 成绩记录迁移）
- `content` ← 文章 / 遇见区短文与预置种子、Anki 导出、音频缓存
- `records` ← 考试 / 训练记录读写（exam_trials / a1_* / listen_trials / hard_sentence_trials）
- `vocab` ← 词汇契约与富字段（A1 工作台词库与**词库缓存**、12 字段契约、reader 富字段回填）

纪律：
- 切片之间与对外一律**绝对导入**（`from delector.core.db.backup import X`）。
- 本 `__init__` 刻意**不 import 任何切片**：保持轻量、避免导入副作用与导入环；
  消费方仍可走 `delector.core.database` 的 façade，或直接走子模块路径。
"""
