# -*- coding: utf-8 -*-
r"""桌面端数据目录 bootstrap（ADR-0019 Q2-A / Q3-B）+ 一次性迁移的行为契约。

事故背景（为什么值得为它单独立一组用例）
--------------------------------------
便携版是 `PyInstaller --onedir`：数据落在**程序目录**里（`database.py` 的 `DATA_DIR`
在桌面端没有 `DELECTOR_DATA_DIR` 兜底 ⇒ 落到 `_REPO_ROOT`）。于是用户「解压新版覆盖
旧目录 / 删掉旧目录」= 学习记录全空**且零提示** —— 而 `preflight_data_dir()` 的条件④
在桌面端恒等（`data_dir == repo_root`），那道闸**永远不会拦**这条路径。

本组用例钉三件事
----------------
1. **优先级不可颠倒**：显式 `DELECTOR_DATA_DIR` > `DELECTOR_PORTABLE=1`（程序目录）>
   `%LOCALAPPDATA%\DeLector`。顺序一旦颠倒，Android（`MainActivity` 注入 env）与
   测试注入会被静默覆盖 —— 那正是「本地全绿、用户丢数据」的同构失败。
2. **幂等**：「迁移 → 新写入 → 重启」三段时序下，第二次调用必须识别「新位置已有数据」
   ⇒ 不重复搬、更**不回退**到旧快照（否则用户在迁移后写的东西会在下次启动时消失）。
3. **绝不半搬**：迁移中途任何异常 ⇒ 旧位置**原封不动**、新位置不留残骸、返回 `False`
   且**写 ERROR 日志**（No-Silent-Failure：此处若 `except: pass`，用户丢数据且无人知情）。

WAL 为什么单独钉（ADR-0019 §7 Unknown 3）
----------------------------------------
库是 WAL 模式（`database.py:147-155`），**已提交但未 checkpoint 的写入只存在于
`delector.db-wal`** ⇒ 只搬主库会丢最近写入，且丢得极其安静（库能打开，只是少几行）。
故用例断言的是**结果**（WAL 里的那一行在新位置读得到），而不是「有没有拷贝某个文件」——
前者对「checkpoint 后搬主库」与「原样搬 -wal/-shm」两种实现都成立，后者会钉死实现。
另有一条强制 checkpoint 失败的用例，钉住退化路径：checkpoint 走不通时必须**连 WAL 一起搬**。

接线为什么也要钉
----------------
`start.py` 顶部 `import uvicorn` / `from delector.server import app` 一旦先跑，
`database.py` 已按仓库根把 `DATA_DIR` 落定，bootstrap 再设 env 也没用了 —— 这是
「代码对了但没生效」的经典失败。故用 AST 断言接线点在**模块顶层**且**早于**任何
`delector.*` 导入（除 bootstrap 自身）。

冒烟纪律（MUST —— 写在这里是因为真的踩过）
----------------------------------------
**任何手工 / 冒烟验证 MUST 先显式把 `DELECTOR_DATA_DIR` 钉到一个临时目录**再跑；
否则 bootstrap 会按平台默认落点（Windows 是 `%LOCALAPPDATA%\DeLector`）执行，并把
仓库根那份**真实库真的搬走**（原件改名成 `delector.db.bak-<时间戳>`）—— 那是带用户
学习记录的文件，搬动它既污染工作区又会在此后每条断言上制造假象。本组用例一律经
tmp_path 注入落点，正是为了不碰真实库。
"""

import ast
import logging
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# 惰性导入（刻意）：模块还不存在时，顶层 `from ... import` 会让 pytest 在**收集期**就
# ImportError 中断，那样只剩 1 条 collection error，看不出「各条契约各自未被满足」。
def _mod() -> Any:
    from delector.core import data_dir_bootstrap

    return data_dir_bootstrap


def _seed(db_path: Path, values: List[str]) -> None:
    """建一张 `notes` 表并写入若干行——迁移后读得到哪几行，就是本次要断言的全部事实。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT)")
        conn.executemany("INSERT INTO notes (text) VALUES (?)", [(v,) for v in values])
        conn.commit()
    finally:
        conn.close()


def _rows(db_path: Path) -> List[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [str(row[0]) for row in conn.execute("SELECT text FROM notes ORDER BY id")]
    finally:
        conn.close()


def _dirs(tmp_path: Path) -> Any:
    legacy = tmp_path / "program"
    target = tmp_path / "appdata"
    legacy.mkdir()
    target.mkdir()
    return legacy, target


# ── 优先级：三分支不可颠倒 ────────────────────────────────────────────────────
def test_explicit_data_dir_env_beats_portable_and_default(tmp_path: Path):
    """① 显式 `DELECTOR_DATA_DIR` 优先于**一切**：`DELECTOR_PORTABLE` 也不得覆盖它。

    Android 由 `MainActivity` 注入该 env、测试也靠它注入隔离库 —— 优先级一旦被便携开关
    压过去，两者都会被静默改到别处（正是本模块要防的那类「本地全绿、用户丢数据」）。
    """
    mod = _mod()
    explicit = tmp_path / "explicit"
    env = {
        "DELECTOR_DATA_DIR": str(explicit),
        "DELECTOR_PORTABLE": "1",
        "LOCALAPPDATA": str(tmp_path / "Local"),
    }

    assert mod.resolve_data_dir(env) == str(explicit)


def test_explicit_data_dir_env_beats_localappdata_default(tmp_path: Path):
    """① > ③：没开便携开关时，显式 env 同样优先于 `%LOCALAPPDATA%` 默认值。"""
    mod = _mod()
    explicit = tmp_path / "explicit"
    env = {"DELECTOR_DATA_DIR": str(explicit), "LOCALAPPDATA": str(tmp_path / "Local")}

    assert mod.resolve_data_dir(env) == str(explicit)


def test_portable_flag_falls_back_to_program_dir(tmp_path: Path):
    """② `DELECTOR_PORTABLE=1` ⇒ 数据回到程序目录（U 盘 / 多机场景，Q3-B）。"""
    mod = _mod()
    env = {"DELECTOR_PORTABLE": "1", "LOCALAPPDATA": str(tmp_path / "Local")}
    resolved = mod.resolve_data_dir(env)

    assert resolved == mod.program_dir(), "便携模式必须回到程序目录（数据随程序走）"
    assert os.path.isdir(resolved), f"程序目录 {resolved} 必须是真实存在的目录"
    assert (tmp_path / "Local").as_posix() not in resolved, "便携模式下不得再落到 LOCALAPPDATA"


def test_program_dir_is_exe_dir_when_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """打包后（`sys.frozen`）程序目录 = **exe 所在目录**，不是 `_internal` 这类实现细节。

    便携模式「数据随程序走」的落点判定**只有这一处**：用户「把整个目录拷到 U 盘」拷的
    正是 exe 那一层，判错一层就回到「删掉这个目录 = 删掉学习记录」。
    """
    mod = _mod()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DeLector" / "DeLector.exe"))

    assert mod.program_dir() == str(tmp_path / "DeLector"), "打包后必须取 exe 所在目录"


def test_portable_flag_uses_exe_dir_when_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """便携开关 + 打包 ⇒ 解析结果落在 exe 旁边（U 盘场景的唯一落点，不得落到 LOCALAPPDATA）。"""
    mod = _mod()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DeLector" / "DeLector.exe"))
    env = {"DELECTOR_PORTABLE": "1", "LOCALAPPDATA": str(tmp_path / "Local")}

    assert mod.resolve_data_dir(env) == str(tmp_path / "DeLector")


def test_default_on_windows_is_localappdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """③ Windows 默认落 `%LOCALAPPDATA%\\DeLector` —— 覆盖/删除程序目录不再等于删数据。

    为何 monkeypatch 的是 `_is_windows` 而不是 `os.name`：`pathlib` 在**被 import 时**
    按 `os.name` 决定 `Path` 是 `WindowsPath` 还是 `PosixPath`；一旦在本会话里把
    `os.name` 临时改成 `posix`，任何此刻首次 import pathlib 的模块都会把 `Path` 永久
    绑成 `PosixPath`（实测：pytest 自己在收尾时 `NotImplementedError: cannot
    instantiate 'PosixPath'`）。故平台分支走一个可替换的小函数，测试钉它。
    """
    mod = _mod()
    monkeypatch.setattr(mod, "_is_windows", lambda: True)
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}

    assert mod.resolve_data_dir(env) == str(tmp_path / "Local" / "DeLector")


def test_default_on_posix_is_xdg_style(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """③ 非 Windows 落 `~/.local/share/DeLector`（Linux/macOS 开发机也别落程序目录）。"""
    mod = _mod()
    monkeypatch.setattr(mod, "_is_windows", lambda: False)
    env = {"HOME": str(tmp_path / "home")}

    assert mod.resolve_data_dir(env) == str(tmp_path / "home" / ".local" / "share" / "DeLector")


# ── 迁移：happy path + 备份 + 幂等 ────────────────────────────────────────────
def test_migration_moves_db_and_leaves_timestamped_backup(tmp_path: Path):
    """首次切换：旧库搬到新位置，旧位置的原件改名成 `*.bak-<时间戳>`（**绝不删**）。

    备份是「搬错了还能回来」的唯一后路；改名而非删除，则保证任何一步失败时原件都还在。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is True

    assert _rows(target / "delector.db") == ["v1"], "旧数据必须在**新**位置读得到"
    assert not (legacy / "delector.db").exists(), "原件应已改名让位，不能两份同时在役"
    backups = sorted(legacy.glob("delector.db.bak-*"))
    assert backups, "迁移必须留下带时间戳的备份，否则搬错一步就不可逆"
    assert _rows(backups[0]) == ["v1"], "备份里必须是迁移**前**的完整数据"


def test_migration_is_idempotent_across_restart(tmp_path: Path):
    """幂等（三段时序：迁移 → 新写入 → 重启）—— 这是本组最重要的用例。

    第二次调用必须识别「新位置已有数据」⇒ 不重复搬。一旦它把旧快照（或备份）又搬回来，
    用户在迁移之后写的东西会在下次启动时**消失**，且消失得毫无征兆。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is True  # 阶段一：迁移

    target_db = target / "delector.db"
    assert _rows(target_db) == ["v1"]

    _seed(target_db, ["v2"])  # 阶段二：用户在新位置继续用（写入 v2）

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is False  # 阶段三：重启
    assert _rows(target_db) == ["v1", "v2"], "重启后必须同时看到迁移来的数据与迁移后新写的"
    assert not (legacy / "delector.db").exists(), "幂等调用不得把旧库再放回原处"


def test_no_migration_when_target_already_has_data(tmp_path: Path):
    """新位置已有库 ⇒ 一律不搬（哪怕旧位置也有库）。数据在新位置，旧的是历史。"""
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["legacy"])
    _seed(target / "delector.db", ["current"])

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is False
    assert _rows(target / "delector.db") == ["current"]
    assert (legacy / "delector.db").exists(), "未发生迁移时旧位置不该被改动"


def test_no_migration_when_legacy_has_no_db(tmp_path: Path):
    """旧位置没有库 ⇒ 全新安装，无需迁移（返回 False，不做任何写操作）。"""
    mod = _mod()
    legacy, target = _dirs(tmp_path)

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is False
    assert list(target.iterdir()) == [], "全新安装不得在新位置留下任何东西"


def test_same_dir_is_never_migrated_onto_itself(tmp_path: Path):
    """旧位置 == 新位置（程序目录即数据目录，便携模式的常态）⇒ 直接不搬。

    复制文件到自身会抛 `SameFileError`；更危险的是「搬到一半」会让同一目录同时存在
    原件与副本。故这条同地短路必须在**建计划之前**发生。
    """
    mod = _mod()
    shared = tmp_path / "shared"
    shared.mkdir()
    _seed(shared / "delector.db", ["v1"])

    assert mod.migrate_legacy_data_dir(str(shared), str(shared)) is False
    assert _rows(shared / "delector.db") == ["v1"]


# ── WAL：只搬主库会丢最近写入 ─────────────────────────────────────────────────
def test_commits_still_in_wal_survive_the_move(tmp_path: Path):
    """WAL 里已提交但未 checkpoint 的写入**必须**跟着一起走（ADR-0019 §7 Unknown 3）。

    断言的是**结果**（那一行在新位置读得到），对「先 checkpoint 再搬主库」与「原样搬
    -wal/-shm」两种实现都成立 —— 只搬主库的那版会在这里转红。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    legacy_db = legacy / "delector.db"

    # 刻意让连接**保持打开**并关掉自动 checkpoint：写入只落在 -wal 里，主库里没有
    conn = sqlite3.connect(str(legacy_db), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO notes (text) VALUES ('in-wal')")
    try:
        wal = legacy / "delector.db-wal"
        assert wal.exists() and wal.stat().st_size > 0, "前提失败：数据没进 WAL，本用例会假绿"

        assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is True
        assert _rows(target / "delector.db") == ["in-wal"], "WAL 里的已提交写入被丢了"
    finally:
        conn.close()


def test_wal_sidecar_is_carried_when_checkpoint_is_impossible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """退化路径：checkpoint 走不通（库损坏 / 磁盘只读）⇒ 必须**连 WAL 侧文件一起搬**。

    把 `sqlite3.connect` 打成抛错即可让 checkpoint 不可用；此时 -wal 里可能就是全部最近
    写入，搬主库而不搬它 = 丢数据。故断言 -wal 必须出现在新位置。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    legacy_db = legacy / "delector.db"

    conn = sqlite3.connect(str(legacy_db), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, text TEXT)")
    conn.execute("INSERT INTO notes (text) VALUES ('in-wal')")
    try:
        assert (legacy / "delector.db-wal").stat().st_size > 0, "前提：WAL 里必须有未落盘的数据"

        def no_sqlite(*_args: Any, **_kwargs: Any) -> Any:
            raise sqlite3.OperationalError("模拟：库无法打开，checkpoint 不可用")

        monkeypatch.setattr(mod.sqlite3, "connect", no_sqlite)

        assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is True
        assert (target / "delector.db-wal").stat().st_size > 0, "checkpoint 失败时必须把 -wal 一起搬走"
    finally:
        conn.close()


# ── 失败语义：绝不半搬 + No-Silent-Failure ───────────────────────────────────
def test_copy_failure_leaves_legacy_intact_and_target_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """中途异常 ⇒ 旧位置**原封不动**、新位置不留残骸、返回 `False`、且写 ERROR 日志。

    「半搬」是最坏结果：新位置有一份不完整的库（程序会用它），旧位置那份被改名/删掉，
    用户两头不到岸。故本用例同时钉四件事，缺一条都算没守住。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])
    _seed(legacy / "progress.db", ["p1"])

    real_copy2 = shutil.copy2
    calls = {"n": 0}

    def flaky_copy2(src: str, dst: str, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise OSError("模拟：磁盘写满")
        return real_copy2(src, dst, **kwargs)

    monkeypatch.setattr(mod.shutil, "copy2", flaky_copy2)

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is False
    assert _rows(legacy / "delector.db") == ["v1"], "旧位置必须原封不动（绝不半搬）"
    assert _rows(legacy / "progress.db") == ["p1"]
    assert list(target.iterdir()) == [], f"新位置不得留残骸，实际有 {list(target.iterdir())}"


def test_failure_is_logged_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """No-Silent-Failure：失败必须有 ERROR 级日志（禁止 `except: pass` 之类吞掉）。

    桌面用户看不到异常栈，日志是唯一的知情渠道；静默失败在这里等价于「数据没了且没人知道」。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：磁盘写满")

    monkeypatch.setattr(mod.shutil, "copy2", boom)
    caplog.set_level(logging.DEBUG)

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is False
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "迁移失败必须留下 ERROR 级日志，否则上层与用户都无从得知"
    assert str(legacy) in errors[0].getMessage(), "日志必须点名旧位置，否则用户不知道去哪儿找数据"


def test_retire_failure_is_logged_as_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """旧库改名备份失败（Windows 上文件被占用 / 杀软锁住）⇒ 必须有 **ERROR** 级信号。

    此时新库已就位、旧库**保持原名**：两份同时在役，而 bootstrap 的「迁移未完成」提示因
    新位置有数据而**不触发** ⇒ 这条日志是唯一线索。若它停在 WARNING，旧库就永久变成孤儿：
    用户以为数据已外置、放心地覆盖安装，实际那份原件才是他一直在写的库。
    """
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])
    caplog.set_level(logging.DEBUG)

    def locked(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：旧库被别的进程占住，改名失败")

    monkeypatch.setattr(mod.os, "replace", locked)

    assert mod.migrate_legacy_data_dir(str(legacy), str(target)) is True
    assert _rows(target / "delector.db") == ["v1"], "新位置的数据是真的（程序会用它）"
    assert _rows(legacy / "delector.db") == ["v1"], "改名失败时旧库保持原名：两份同时在役，必须有人知道"

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "旧库没能退役必须报 ERROR：只报 WARNING 它会永远是个没人知道的孤儿"
    assert str(legacy / "delector.db") in errors[0].getMessage(), "日志必须点名那份没退役的旧库"


# ── 接线：start.py 必须在 import server 之前 bootstrap ────────────────────────
def _start_py_tree() -> ast.Module:
    return ast.parse((REPO_ROOT / "start.py").read_text(encoding="utf-8"))


def _is_bootstrap_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "bootstrap_data_dir"


def _is_delector_import(node: ast.AST) -> bool:
    """`delector.*` 的导入——排除 bootstrap 自身（它必须**先**被导入才能被调用）。"""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return module.startswith("delector") and module != "delector.core.data_dir_bootstrap"
    if isinstance(node, ast.Import):
        return any(a.name.startswith("delector") and a.name != "delector.core.data_dir_bootstrap" for a in node.names)
    return False


def _mentions_database(node: ast.AST) -> bool:
    """该导入是否指向 `database` 模块（只看最后一段，兼容 `import a.b.database` 两种写法）。"""
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[-1] == "database"
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[-1] == "database" for a in node.names)
    return False


def _bootstrap_calls(tree: ast.Module) -> List[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_bootstrap_call(n)]


def _delector_imports(tree: ast.Module) -> List[ast.stmt]:
    return [
        n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and _is_delector_import(n)
    ]


def test_start_py_bootstrap_runs_inside_main_before_the_server_import():
    """接线必须在 `main()` 内、且早于 `from delector.server import app`。

    为什么钉"在 `main()` 内"而不是"模块顶层"：`main()` 是**所有**入口（脚本 / Android /
    日后的桌面壳）的共同路径，放这里才不会漏；而模块顶层语句在 `import start` 时**也会跑**
    —— `tests/test_start.py` 就在 import start，那会污染整个 pytest 进程的 env
    （DELECTOR_DATA_DIR 被写成真实的 %LOCALAPPDATA% 落点）。
    """
    tree = _start_py_tree()
    main_fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert main_fn is not None, "start.py 里找不到 main()（前提变了，本用例需重写）"

    calls: List[ast.Call] = [n for n in ast.walk(main_fn) if isinstance(n, ast.Call) and _is_bootstrap_call(n)]
    server_imports: List[ast.ImportFrom] = [
        n for n in ast.walk(main_fn) if isinstance(n, ast.ImportFrom) and (n.module or "") == "delector.server"
    ]

    assert calls, "main() 里找不到 bootstrap_data_dir 调用：数据会落回程序目录"
    assert server_imports, "前提变了：main() 里找不到 `from delector.server import app`"
    assert min(n.lineno for n in calls) < min(n.lineno for n in server_imports), (
        "bootstrap_data_dir 必须排在 `from delector.server import app` 之前（晚一步就永久失效）"
    )

    # 反向钉：模块顶层**不得**有该调用（`import start` 会执行它 → 污染 pytest 进程 env）。
    # 用源码断言而不是 import 后查 env：后者在 start 已被别的用例导入过时会变成假绿。
    outside = [stmt for stmt in tree.body if stmt is not main_fn and any(_is_bootstrap_call(n) for n in ast.walk(stmt))]
    assert not outside, "bootstrap_data_dir 不得出现在模块顶层：import start 会顺手改 env、建目录、甚至搬库"


def test_start_py_bootstrap_precedes_every_delector_import():
    """源码顺序：bootstrap 调用必须早于**任何** `delector.*` 导入（含 `delector.server`）。

    `from delector.server import app` 一跑，`database.py` 的 `DATA_DIR` 就按仓库根落定了，
    之后再设 `DELECTOR_DATA_DIR` 毫无作用 —— 这是「代码对了但没生效」的经典失败，
    只能靠源码顺序断言钉住（运行时断言会被 import 缓存掩盖）。
    """
    tree = _start_py_tree()
    bootstrap = _bootstrap_calls(tree)
    delector_imports = _delector_imports(tree)

    assert bootstrap, "start.py 里找不到 bootstrap_data_dir 调用"
    assert delector_imports, "start.py 里找不到 delector.* 导入（前提变了，本用例需重写）"
    assert min(n.lineno for n in bootstrap) < min(n.lineno for n in delector_imports), (
        "bootstrap_data_dir 的调用必须排在 delector.* 导入之前"
    )


def test_bootstrap_module_does_not_import_database_at_module_level():
    """bootstrap 模块自身**不得**在模块级 import `database`：那会在设 env 之前冻结 DATA_DIR。

    这不是洁癖：`database` 在被 import 的瞬间就按「当时的 env」算出 `DATA_DIR`，
    bootstrap 若把它带到模块顶层，落点就永远停在旧位置 —— 测试全绿、用户照旧丢数据。
    """
    path = REPO_ROOT / "delector" / "core" / "data_dir_bootstrap.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    offenders = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and _mentions_database(n)]
    assert not offenders, "data_dir_bootstrap 不得在模块级导入 database（会抢在设 env 之前冻结 DATA_DIR）"


def test_legacy_dir_matches_database_repo_root():
    """bootstrap 推导的旧落点必须与 `database._REPO_ROOT` **恒等**：搬错起点 = 搬不到数据。

    bootstrap 刻意不 import `database`（否则 `start.py` 的「端口已占用 ⇒ 直接开浏览器」
    快路径要先拉起 spacy 链路），代价是两个模块各算一次目录、靠"同处 `delector/core/`"
    这一事实保持一致。谁挪了文件，两边就会静默错位 —— 这条用例把耦合钉死。
    """
    from delector.core.database import _REPO_ROOT

    mod = _mod()
    assert os.path.normpath(mod.legacy_data_dir()) == os.path.normpath(str(_REPO_ROOT))


# ── bootstrap 组装：写回 env、不覆盖显式值、不动移动端 ────────────────────────
def test_bootstrap_sets_env_and_migrates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """端到端组装：解析 → 建目录 → 写回 env → 迁移，返回最终落点。"""
    mod = _mod()
    monkeypatch.setattr(mod, "_is_windows", lambda: True)
    legacy, _ = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}

    resolved = mod.bootstrap_data_dir(env, legacy_dir=str(legacy))
    expected = str(tmp_path / "Local" / "DeLector")

    assert resolved == expected
    assert env["DELECTOR_DATA_DIR"] == expected, "bootstrap 必须把决定写回 env，供 database 读取"
    assert _rows(Path(expected) / "delector.db") == ["v1"]


def test_bootstrap_keeps_explicit_env(tmp_path: Path):
    """调用方已显式设 `DELECTOR_DATA_DIR` ⇒ bootstrap 原样保留（Android / 测试注入）。"""
    mod = _mod()
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    env = {"DELECTOR_DATA_DIR": str(explicit)}

    assert mod.bootstrap_data_dir(env, legacy_dir=str(tmp_path / "legacy")) == str(explicit)
    assert env["DELECTOR_DATA_DIR"] == str(explicit)


def test_bootstrap_leaves_android_alone(monkeypatch: pytest.MonkeyPatch):
    """Android 的落点由 `MainActivity` 注入；start.py 不该替它猜一个桌面路径。"""
    mod = _mod()
    monkeypatch.setattr(mod, "is_android", lambda: True)
    env = {"ANDROID_ROOT": "/system"}

    assert mod.bootstrap_data_dir(env) == ""
    assert "DELECTOR_DATA_DIR" not in env, "移动端未被注入时不得由桌面逻辑擅自写入落点"


def test_bootstrap_falls_back_to_legacy_when_target_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """新位置建不出来（权限/路径不存在）⇒ 回退到旧位置**并记 ERROR**，而不是崩在原地。

    静默空库被 ADR-0019 判为最坏结果，但「起不来」同样不可接受：回退到旧落点至少
    保留原有行为，且错误信息指明后果（数据仍随程序目录）。

    这里刻意**不**设 `DELECTOR_DATA_DIR`：回退只允许改写「本模块自己算出来的落点」，
    显式值被改写的情形由下一条用例单独钉住（硬约束③在失败路径上同样生效）。
    """
    mod = _mod()
    monkeypatch.setattr(mod, "_is_windows", lambda: True)
    legacy, _ = _dirs(tmp_path)
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    caplog.set_level(logging.DEBUG)

    def no_makedirs(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：目标目录不可建")

    monkeypatch.setattr(mod.os, "makedirs", no_makedirs)

    assert mod.bootstrap_data_dir(env, legacy_dir=str(legacy)) == str(legacy)
    assert env["DELECTOR_DATA_DIR"] == str(legacy)
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "回退必须伴随 ERROR 日志，否则用户不知道数据仍在旧位置（删目录会丢）"


def test_bootstrap_keeps_explicit_env_when_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """显式落点**建不出来**时同样不得改写 env：只记 ERROR，把 fail-loud 交给 `database`。

    硬约束③（显式优先）在失败路径上也必须成立：`resolve_data_dir` 里的「显式优先」若被
    fallback 分支反过来覆盖，用户 / Android 宿主注入的落点就被静默换掉了 —— 而「显式
    指定 env」正是用户表达「我要放这里」的唯一手段；此时由 `database` 在建库时硬失败，
    也比被悄悄改到别处好（前者看得见，后者是「本地全绿、数据不在我以为的地方」）。
    """
    mod = _mod()
    explicit = tmp_path / "explicit-dead-end"
    env = {"DELECTOR_DATA_DIR": str(explicit), "LOCALAPPDATA": str(tmp_path / "Local")}
    caplog.set_level(logging.DEBUG)

    def no_makedirs(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：目标目录不可建")

    monkeypatch.setattr(mod.os, "makedirs", no_makedirs)

    assert mod.bootstrap_data_dir(env, legacy_dir=str(tmp_path / "legacy")) == str(explicit)
    assert env["DELECTOR_DATA_DIR"] == str(explicit), "显式值不得被回退逻辑覆盖（用户的选择优先）"

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "不可用的显式落点必须留下 ERROR 日志，否则用户以为数据已被放到别处"
    assert str(explicit) in errors[0].getMessage(), "日志必须点名那个不可用的落点"


def test_bootstrap_falls_back_to_legacy_when_migration_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """`makedirs` 成功、但迁移写不进去（配额 / ACL / 网络重定向离线）⇒ **同样回退**旧位置。

    「目录建得出来就认新位置」是不一致的失败策略：此时 env 指向一个**空且不可写**的目录，
    `init_db` 要么崩在原地、要么建出一个空库，而真正的库还留在旧位置（下次覆盖安装就没了）。
    故失败策略只有一套 —— **落不稳就回到旧的**，与「目录建不出来」那条路径一致。
    """
    mod = _mod()
    monkeypatch.setattr(mod, "_is_windows", lambda: True)
    legacy, _ = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    caplog.set_level(logging.DEBUG)

    def no_copy(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：写入被拒（配额 / ACL）")

    monkeypatch.setattr(mod.shutil, "copy2", no_copy)

    target = tmp_path / "Local" / "DeLector"

    assert mod.bootstrap_data_dir(env, legacy_dir=str(legacy)) == str(legacy)
    assert env["DELECTOR_DATA_DIR"] == str(legacy), "迁移没落稳就不得让 env 指向空的新位置"
    assert not (target / "delector.db").exists(), "回退后新位置不得留下会被当成真数据的残骸"
    assert _rows(legacy / "delector.db") == ["v1"], "旧库必须原封不动（它是此刻唯一有效的数据）"

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "回退必须伴随 ERROR 日志，否则用户不知道数据仍在旧位置"


def test_bootstrap_keeps_explicit_env_when_migration_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """显式落点 + 迁移失败 ⇒ 仍然不动 env（与②同一条硬约束，只是失败点不同）。"""
    mod = _mod()
    legacy, target = _dirs(tmp_path)
    _seed(legacy / "delector.db", ["v1"])
    env = {"DELECTOR_DATA_DIR": str(target)}

    def no_copy(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("模拟：写入被拒（配额 / ACL）")

    monkeypatch.setattr(mod.shutil, "copy2", no_copy)

    assert mod.bootstrap_data_dir(env, legacy_dir=str(legacy)) == str(target)
    assert env["DELECTOR_DATA_DIR"] == str(target), "显式值不得因迁移失败被换成旧落点"
