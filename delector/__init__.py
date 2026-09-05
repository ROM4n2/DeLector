# -*- coding: utf-8 -*-
"""DeLector 后端包。

Phase 2 把根目录 26 个扁平业务模块收进这里。根目录只留入口（`start.py`）、
打包工具（`package_windows.py`）与 pytest 用的 `conftest.py`。

两条纪律（都是踩过才知道疼的）：

1. **包内不要把 `os.path.dirname(__file__)` 当成"仓库根"** —— 那是本包目录。
   `database.py` 的 `DATA_DIR` 一度就是这么写的，结果 `delector.db` /
   `progress.db` 整体搬家，用户数据表现为"升级后全没了"，而本地测试全绿。
   需要仓库根就显式回指一级，并由 `tests/test_backend_package_layout.py` 钉住。

2. **静态资源不进包**，留在仓库根 `static/`，由 `server.py` 的回退链去解析。
   跟着模块一起搬会让回退链指向 `delector/static`（不存在）。
"""
