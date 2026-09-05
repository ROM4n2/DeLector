# -*- coding: utf-8 -*-
"""Phase 1 迁移哨兵：tests/ 下的测试必须能 import 仓库根目录的扁平业务模块。

为什么值得单独钉住一条：CI 与本地都跑 `pytest -v`，而 `pytest` 不像
`python -m pytest` 那样把当前工作目录加进 sys.path。测试搬进 `tests/`
之后，pytest 只会把 `tests/` 自身插进 sys.path，根目录的 `server.py` /
`database.py` 等扁平模块会**全部不可见** —— 不是某一条测试红，而是
27 个测试在 import 阶段集体 ModuleNotFoundError。

这个失败还有一个更坏的形态：它看起来像"代码坏了"而不是"路径没配"，
排查时容易往业务代码里钻。用一条独立哨兵把"路径接线"和"业务正确"
分开，迁移期任何一步接错都会立刻指向这里。
"""


def test_tests_dir_can_import_root_flat_modules():
    import server
    from delector import database  # noqa: F401  — 证明不止 server 一个模块可见

    assert hasattr(server, "app"), "import 到的 server 没暴露 app（可能 import 到同名假模块）"
