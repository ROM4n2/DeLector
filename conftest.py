# -*- coding: utf-8 -*-
"""根 conftest：把仓库根目录插进 sys.path，让 tests/ 下的测试能 import 扁平业务模块。

为什么必须有这个文件：CI 与本地都跑 `pytest -v`，而 `pytest` 不像
`python -m pytest` 那样把当前工作目录加进 sys.path。测试搬进 `tests/`
之后 pytest 只把 `tests/` 自身插进 sys.path，根目录的 `server.py` /
`database.py` 等扁平模块全部不可见 —— 27 个测试会在 import 阶段集体
ModuleNotFoundError，且报错长得像业务代码坏了，很容易查错方向。

Phase 2 把业务模块收进 `delector/` 包之后，这里就该删掉（包内相对 import
不再需要系统路径注入）。留着它不会坏，但会让"到底哪些模块是扁平的"这件事
继续含糊 —— 删它应该是 Phase 2 的验收条件之一。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
