# -*- coding: utf-8 -*-
"""数据目录迁移闸（Task 1 / P0-1）：旧版单文件挂载升级后的**静默空库**必须变成响亮崩溃。

事故链
------
`docker-compose.yml` 早期把卷挂成单文件 ``./delector.db:/app/delector.db``，后来改成目录
``./data:/app/data`` 并**无条件**设 ``DELECTOR_DATA_DIR=/app/data``。而
`database.py` 的 `DATA_DIR = os.environ.get("DELECTOR_DATA_DIR", _REPO_ROOT)` 与
`get_db_path()`（``DATABASE_PATH`` → ``DATA_DIR/delector.db``）意味着：存量用户升级后
旧库**不再被挂进容器**，而 ``init_db()`` 只会建一套空 schema ⇒ 用户打开应用，
功能一切正常，**数据全空**，且全仓没有任何探测、告警或迁移说明。

更糟的失败模式
--------------
空库一旦被创建，用户的诊断直觉会是「数据丢了」；但审计已核实**数据文件根本没被删除**，
只差一次 ``cp``。于是「静默空库」比「响亮崩溃」危险得多：前者让用户做不可逆的
「恢复出厂」操作，后者只需要照着日志抄一条命令。

故本模块钉住 fail-loud 语义
---------------------------
`preflight_data_dir(data_dir, repo_root)` 是**纯只读**的启动自检：新位置无库 **且**
旧位置有**非空**库 ⇒ 抛 `RuntimeError`，消息里带两个绝对路径和一条可直接复制的
``cp`` 命令。绝不代用户搬文件（No-Silent-Write：启动路径上不做用户没要求的写操作），
也绝不 `logging.warning` 后继续建空库（Fail-Loud）。

八条行为用例的分工（另有两条补充用例见下）
----------------------------------------
① 事故形态 ⇒ 抛；② size==0 的空壳文件不算数据（Honest-Null，旧位置）；
③ 桌面端默认 ``DATA_DIR == _REPO_ROOT`` **绝不能误报**（最危险的回归）；
③' 两路径同地 + 共享库 **0 字节** ⇒ 仍**不**抛（①/② 不再互斥后，条件④ 真正被执行的那条路径）；
④ 新位置已有库 ⇒ 一切正常，不拦；⑤ 旧位置只剩 Docker 建的同名**目录** ⇒ 不拦
（`isfile` 语义，事故现场在 Linux 容器内）；⑥ 新位置是**目录** ⇒ 算「无库」，交回旧位置判据；
⑥' 新位置是**目录** + 旧位置**非空** ⇒ **抛**（`isfile` 对目录返回 False 的既有设计决定）；
⑦ 新位置 0 字节空壳 + 旧位置有数据 ⇒ **仍抛**（size 对称化，堵住静默空库）；
⑧ 新位置**非空** + 旧位置非空 ⇒ 不抛（对称性守卫，防改到另一极端）。
另有 2 条接线/状态用例：模块级 ``DATA_DIR`` 与 ``_REPO_ROOT`` 同地、``init_db()`` 先跑闸后建表。
"""

import os
from pathlib import Path
from typing import Callable

import pytest


# 惰性导入（刻意）：`preflight_data_dir` 还不存在时，顶层 `from ... import` 会让 pytest 在
# **收集期**就 ImportError 中断，那样只剩 1 条 collection error，看不出「4 个行为契约各自
# 未被满足」。惰性导入让 4 条用例**各自独立**红在真实断言上。
def _preflight() -> Callable[[str, str], None]:
    from delector.core.database import preflight_data_dir

    return preflight_data_dir


def _make_repo_root(tmp_path: Path, *, legacy_bytes: bytes | None) -> Path:
    """造一个「仓库根」，按需在下面放一个旧位置的 delector.db。"""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    if legacy_bytes is not None:
        (repo_root / "delector.db").write_bytes(legacy_bytes)
    return repo_root


def _patch_dir_size_linux_semantics(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 `os.path.getsize(<目录>)` 报 4096，模拟 Linux 的 `st_size`（Windows 恒 0）。

    迁移闸的事故现场在 **Linux 容器**内；`os.path.getsize` 对目录的值是平台相关的
    （Windows 返回 0，Linux 返回 4096），而闸的 size 判据必须靠 `isfile` 而**不是**
    size 把目录排除掉。不做这层模拟，用例就会在 Windows 上假绿（见用例⑤ 的说明）。
    只影响目录，普通文件的真实字节数原样透传。
    """
    real_getsize = os.path.getsize

    def getsize(path: str) -> int:
        return 4096 if os.path.isdir(path) else real_getsize(path)

    monkeypatch.setattr(os.path, "getsize", getsize)


def test_legacy_nonempty_db_with_empty_new_dir_raises_with_copy_command(tmp_path: Path):
    """① 事故形态：新位置无库 + 旧位置**非空** ⇒ 抛错，且消息含两个路径与可复制的 cp。"""
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"SQLite format 3\x00legacy rows")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    new_db = data_dir / "delector.db"
    old_db = repo_root / "delector.db"

    assert not new_db.exists(), "前提：新位置必须没有库"

    with pytest.raises(RuntimeError) as excinfo:
        _preflight()(str(data_dir), str(repo_root))

    message = str(excinfo.value)
    assert str(old_db) in message, f"错误消息必须指出旧位置的实际路径，实际为：{message}"
    assert str(new_db) in message, f"错误消息必须指出新位置的实际路径，实际为：{message}"
    assert "cp " in message, f"错误消息必须给出可直接复制的 cp 命令，实际为：{message}"
    assert f'cp "{old_db}" "{new_db}"' in message, (
        f"错误消息里的 cp 命令必须把旧库拷到新库（可直接复制粘贴执行），实际为：{message}"
    )


def test_empty_legacy_file_is_treated_as_no_data(tmp_path: Path):
    """② 旧位置文件 size==0 ⇒ **不**抛。空文件是初始化残留，不是数据。"""
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    assert (repo_root / "delector.db").stat().st_size == 0, "前提：旧文件必须是 0 字节"

    _preflight()(str(data_dir), str(repo_root))  # 不抛即通过


def test_desktop_default_data_dir_equals_repo_root_never_fires(tmp_path: Path):
    """③ 桌面端默认 DATA_DIR == _REPO_ROOT ⇒ **绝不**误报。

    这是最危险的回归：桌面端没有 DELECTOR_DATA_DIR，两个路径规范化后相同，
    条件 4 不成立。若闸在这里开火，**所有**桌面用户都起不来。
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "delector.db").write_bytes(b"SQLite format 3\x00rows")

    _preflight()(str(shared), str(shared))  # data_dir == repo_root，不抛即通过


def test_desktop_shared_empty_db_still_does_not_fire(tmp_path: Path):
    """③' 两路径**同地** + 共享 `delector.db` 为 **0 字节** ⇒ **绝不**误报。

    这是「①/② 不再是互斥」这个**新事实**的守卫，也是条件④ **唯一被真正执行**的那条路径：
    条件① 加了 `size > 0` 后，0 字节共享文件不再让 ① 提前 `return`（`size == 0` 不成立），
    而条件② 只看 `isfile`（文件确实存在）也不返回 ⇒ 控制流**真的**落到条件④ 并由它 `return`。
    用例③（`test_desktop_default_data_dir_equals_repo_root_never_fires`）用的是**非空**共享
    文件 —— 那条走 ① 早退，永远到不了 ④。本条补上的正是 ④ 的实际执行路径，钉住它的唯一
    职责：桌面端两路径同地时**绝不**误报（否则所有桌面用户都起不来）。
    """
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "delector.db").write_bytes(b"")  # 共享文件：0 字节空壳

    assert (shared / "delector.db").stat().st_size == 0, "前提：共享文件必须是 0 字节"

    _preflight()(str(shared), str(shared))  # data_dir == repo_root，不抛即通过


def test_new_location_directory_with_nonempty_old_db_raises(tmp_path: Path):
    """⑥' 新位置是**目录** + 旧位置**非空** ⇒ **抛**：`isfile` 对目录返回 False 是既有设计决定。

    与用例⑥（新位置目录 + 旧位置**无**库 ⇒ 不抛）互补：`isfile` 语义下目录一律算「新位置
    无库」，于是旧位置的非空真实数据会让四条件全中 ⇒ 必须拦（否则又是一次静默空库）。
    这里 `isfile` 对目录返回 `False` 是**刻意**的（见用例⑤：目录残留不是数据），本条把这条
    设计决定在新位置一侧也钉住 —— 若有人把判据退回 `os.path.exists`，本用例立刻转红。
    """
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"SQLite format 3\x00legacy rows")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "delector.db").mkdir()  # 新位置：目录，不是库文件

    assert (data_dir / "delector.db").is_dir(), "前提：新位置必须是目录"

    with pytest.raises(RuntimeError):
        _preflight()(str(data_dir), str(repo_root))


def test_existing_new_db_means_no_obstacle(tmp_path: Path):
    """④ 旧位置非空但新位置**已有**库 ⇒ **不**抛（数据已在位，闸无话可说）。"""
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"SQLite format 3\x00legacy")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "delector.db").write_bytes(b"SQLite format 3\x00current")

    _preflight()(str(data_dir), str(repo_root))  # 不抛即通过


def test_legacy_directory_does_not_block_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """⑤ 旧位置是**目录**（不是库文件）⇒ **不**抛：docker 挂载事故的同名目录残留。

    事故形态：旧版 compose 把卷挂成**单文件** `./delector.db:/app/delector.db`，而宿主文件
    不存在时 Docker 会**自动建一个同名目录** `./delector.db/`。它又被 `Dockerfile` 的
    `COPY . .` 带进镜像，落在 `/app/delector.db`；Linux 下目录 `st_size == 4096 > 0`
    ⇒ 若判据用 `os.path.exists` + `getsize > 0`，**四条件全部成立**，用户被拦死，
    而消息里的 `cp /app/delector.db /app/data/delector.db` 还会报 `omitting a directory`。
    目录里根本没有数据，拦它是纯粹的用户伤害 ⇒ 判据必须是 `os.path.isfile`。

    为何要 monkeypatch `os.path.getsize`
    ------------------------------------
    事故发生在 **Linux 容器**里，而 Windows 上 `os.path.getsize(<目录>)` 返回 **0**
    （实测确认），于是「目录 + size 判据」在 Windows 上被 size 守卫**顺手救回**，
    判据写成 `exists` 也会让本用例变绿 ⇒ 纯文件系统夹具是**假绿**，钉不住任何东西。
    故这里模拟 Linux 语义：目录的 `st_size` 取 4096，让「存在性判据用 exists 还是 isfile」
    成为唯一变量——把它退回 `exists`，本用例立刻转红。
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "delector.db").mkdir()  # 旧位置：Docker 自动建的同名目录
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    assert (repo_root / "delector.db").is_dir(), "前提：旧位置必须是目录"
    _patch_dir_size_linux_semantics(monkeypatch)

    _preflight()(str(data_dir), str(repo_root))  # 不抛即通过


def test_new_location_directory_counts_as_no_db_and_old_location_decides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """⑥ 新位置是**目录** ⇒ 按 `isfile` 语义算「无库」，闸继续看旧位置。

    真实期望（`isfile` 语义下的诚实推论，不臆造）：新位置 `data_dir/delector.db` 是目录
    ⇒ 条件① 判为「新位置无库」；随后旧位置也没有库文件 ⇒ 条件② 不成立 ⇒ **直接 return，
    不抛**。这里刻意**只**钉住「不抛」这一个可观测结果——目录不算库，但闸也不会
    就此替用户做别的判断，它只是把决定权交回旧位置那一条判据。

    注意本条**不**能区分 `exists` 与 `isfile`（两种写法都落到「不抛」）：存在性判据选错的
    危害由用例⑤承担，这里只负责把 `isfile` 语义下新位置目录的**真实结果**钉在案上。
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "delector.db").mkdir()  # 新位置：目录，不是库文件

    assert (data_dir / "delector.db").is_dir(), "前提：新位置必须是目录"
    assert not (repo_root / "delector.db").exists(), "前提：旧位置必须没有库"
    _patch_dir_size_linux_semantics(monkeypatch)

    _preflight()(str(data_dir), str(repo_root))  # 不抛即通过


def test_empty_new_db_does_not_pass_the_gate_when_legacy_has_data(tmp_path: Path):
    """⑦ 新位置是 **0 字节空壳** + 旧位置非空 ⇒ **仍抛**（size 判据在两个位置对称）。

    这是被修的洞：旧版条件① 只 `isfile` **不看 size** ⇒ 新位置一个 0 字节 `delector.db`
    就让闸提前 `return`，旧位置的真实数据被静默忽略，程序随即在新位置重建空库——正是
    本闸（「新位置放空壳 + 旧位置有数据时报静默空库」）要防的场景。对称化后，0 字节空壳
    （初始化残留在**任意位置**都算不上数据）不再让条件① 成立，闸照常开火。
    """
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"SQLite format 3\x00legacy rows")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "delector.db").write_bytes(b"")  # 新位置：0 字节空壳

    assert (data_dir / "delector.db").stat().st_size == 0, "前提：新位置必须是 0 字节"

    with pytest.raises(RuntimeError) as excinfo:
        _preflight()(str(data_dir), str(repo_root))

    assert "cp " in str(excinfo.value), f"错误消息必须仍给出可复制的 cp 命令，实际为：{excinfo.value}"


def test_nonempty_new_db_passes_the_gate(tmp_path: Path):
    """⑧ 对称性：新位置**非空** + 旧位置非空 ⇒ **不抛**（条件① 凭非空库合法通过）。

    与用例④（`test_existing_new_db_means_no_obstacle`，同样非空）呼应，但把「非空」这一
    前提**明确**钉住：数据确实已在新位置 ⇒ 闸无话可说。它同时是「对称化没有把闸改到
    另一个极端」的守卫——非空新库必须放行，否则所有迁移已完成的用户都起不来。
    """
    repo_root = _make_repo_root(tmp_path, legacy_bytes=b"SQLite format 3\x00legacy")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "delector.db").write_bytes(b"SQLite format 3\x00current")

    assert (data_dir / "delector.db").stat().st_size > 0, "前提：新位置必须非空"

    _preflight()(str(data_dir), str(repo_root))  # 不抛即通过


def test_module_level_repo_root_and_data_dir_agree_on_desktop():
    """桌面端不设 DELECTOR_DATA_DIR 时，模块级 DATA_DIR 与 _REPO_ROOT 规范化后必须相同。

    用例③ 已在 tmp_path 上钉住「参数相同不报」；这条补上「真实模块状态也如此」，
    防止有人改了 `DATA_DIR` 的默认值推导方式而两个测试夹具仍各自为政。
    """
    if os.environ.get("DELECTOR_DATA_DIR"):
        pytest.skip("本次运行显式设了 DELECTOR_DATA_DIR，默认路径不生效，跳过")

    from delector.core.database import _REPO_ROOT, DATA_DIR

    assert os.path.normpath(os.path.abspath(DATA_DIR)) == os.path.normpath(os.path.abspath(_REPO_ROOT))


def test_init_db_runs_the_gate_before_creating_any_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`init_db()` MUST 在**建表之前**跑迁移闸——否则空库文件已落盘，闸再响也晚了。

    这条钉的是**接线**，不是闸本身：四条行为用例全绿也可能是因为 `init_db()` 压根没调用它。
    造出事故现场（DATA_DIR 指向空目录、_REPO_ROOT 有非空旧库），断言 `init_db()` 抛错
    **且新位置没有落下任何 .db 文件**——后者证明拒绝发生在建表之前而非之后。
    """
    import delector.core.database as database

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "delector.db").write_bytes(b"SQLite format 3\x00legacy rows")
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(database, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(database, "_REPO_ROOT", str(repo_root))
    monkeypatch.delenv("DELECTOR_DATA_DIR", raising=False)
    # 显式库路径不参与判据（见 init_db 内注释），故必须让它回落到 DATA_DIR 才会走闸
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("PROGRESS_DB_PATH", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        database.init_db()

    assert "cp " in str(excinfo.value)
    assert not (data_dir / "delector.db").exists(), (
        "闸必须在建表之前中止：一旦 CREATE TABLE 执行，空库文件就落盘了，"
        "用户看到的正是「功能正常、数据全空」且此后更难分辨的静默失败。"
    )
