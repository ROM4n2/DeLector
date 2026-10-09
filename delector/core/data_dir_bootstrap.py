# -*- coding: utf-8 -*-
r"""桌面端数据目录 bootstrap：决定落点 + 一次性迁移旧数据。**只做这两件事**。

为什么需要它
------------
便携版是 `PyInstaller --onedir`，而 `database.py` 的 `DATA_DIR` 在桌面端**没有**
`DELECTOR_DATA_DIR` 兜底 ⇒ 数据落在程序目录里。于是用户「解压新版覆盖旧目录 / 删掉
旧目录」= 学习记录全空**且零提示**；更糟的是 `preflight_data_dir()` 的条件④在桌面端
恒等（`data_dir == repo_root`），那道闸**永远拦不到**这条路径（ADR-0019 §1.2）。

故本模块负责：**① 决定落点**（`resolve_data_dir`）与 **② 首次切换时把旧库搬过去**
（`migrate_legacy_data_dir`）—— 让「外置」从「换个地方重建空库」变成「原样搬过去」。

三条不可动摇的优先级（顺序一旦颠倒就是静默丢数据）
------------------------------------------------
1. **已显式设 `DELECTOR_DATA_DIR` ⇒ 原样采用**。Android 由 `MainActivity` 注入它，
   测试也靠它注入隔离库；任何"更聪明"的默认值覆盖掉它都是事故。
2. **`DELECTOR_PORTABLE=1` ⇒ 回到程序目录**（U 盘 / 多机场景，ADR-0019 Q3-B）。
3. 否则 Windows 落 `%LOCALAPPDATA%\DeLector`、其它平台落 `~/.local/share/DeLector`。

迁移为什么"先复制、再改名"，而不是"先备份、再移动"
--------------------------------------------------
`shutil.copy2` 到新位置成功之后，才把旧位置的原件 `os.replace` 成 `*.bak-<时间戳>`。
这样**任何一步失败时原件都还在原处**（不存在"移动了一半"的中间态），而备份天然就是
原件本身，不需要再拷一份。反过来（先备份再 move）在备份阶段就要多写一遍全量数据，
且 move 中断时会留下半截文件。旧文件**永不删除**：删它是用户确认之后的决定。

WAL 为什么必须单独处理
----------------------
库是 WAL 模式（`database.py:147-155`）：**已提交但未 checkpoint 的写入只存在于
`delector.db-wal`**，只搬主库会丢掉最近写入，而且丢得极安静（库能开、只是少几行）。
故先试着 `PRAGMA wal_checkpoint(TRUNCATE)` 把 WAL 折回主库；它失败（库损坏 / 只读 /
被别的进程占住）时，退化成**连 `-wal` 与 `-shm` 成套搬运**（SQLite 官方要求成套）。

不做什么（写死以防悄悄重开）
----------------------------
- **不改** `database.py` 的 `DATA_DIR` 语义、`preflight_data_dir()`、任何 SQL；
- **不做**"迁移失败就拒绝启动"：ADR-0019 §5 明确指出那会让用户「升级后打不开且不知道
  为什么」。失败是**记 ERROR 日志 + 返回 False**，程序照常在新位置启动。

冒烟纪律（MUST —— 写在这里是因为真的踩过）
------------------------------------------
**任何手工 / 冒烟验证 MUST 先显式把 `DELECTOR_DATA_DIR` 钉到一个临时目录**再跑；否则
本模块会按平台默认落点（Windows 是 `%LOCALAPPDATA%\DeLector`）执行，并把仓库根那份
**真实库真的搬走**（原件改名成 `delector.db.bak-<时间戳>`）—— 那是带用户学习记录的文件，
既污染工作区（未跟踪的大文件，`git add -A` 有被提交的风险），也会在此后的每条断言上
制造假象。同理，迁移留下的 `*.bak-*` 也已在 `.gitignore` 里单独忽略。
"""

import logging
import os
import shutil
import sqlite3
import sys
import time
from typing import List, Mapping, MutableMapping, Optional, Tuple

from delector.core.utils import is_android

_LOGGER = logging.getLogger("delector.data_dir")

DATA_DIR_ENV = "DELECTOR_DATA_DIR"
PORTABLE_ENV = "DELECTOR_PORTABLE"
APP_DIR_NAME = "DeLector"

# 需要搬的库文件：`progress.db` 是独立的库（见 database.PROGRESS_DB_PATH），不是主库的一部分
DB_FILE_NAMES: Tuple[str, ...] = ("delector.db", "progress.db")
# WAL 侧文件：`-wal` 里可能有已提交但未落盘的写入；`-shm` 无数据，但 SQLite 官方要求与 -wal 成套搬运
WAL_SUFFIX = "-wal"
SHM_SUFFIX = "-shm"

_PORTABLE_TRUE = ("1", "true")


def _is_windows() -> bool:
    """平台判据单独成函数：测试要能替换它（直接 patch `os.name` 会污染 pathlib，见测试注释）。"""
    return os.name == "nt"


def _package_root() -> str:
    """程序包所在的根：`delector/` 的**父目录**（与 `database._REPO_ROOT` 同算法、同起点）。

    用"向上走到不再是 Python 包目录（无 `__init__.py`）"求根，避免硬编码 dirname 层数。
    本文件与 `database.py` 同在 `delector/core/` 下 ⇒ 两者结果恒等（由
    `tests/test_desktop_data_dir_bootstrap.py::test_legacy_dir_matches_database_repo_root`
    钉住）——**挪动本文件时必须同步改那条用例**。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    while os.path.exists(os.path.join(here, "__init__.py")):
        parent = os.path.dirname(here)
        if parent == here:  # 已到文件系统根，不能再往上
            break
        here = parent
    return here


def program_dir() -> str:
    """程序目录（便携模式的落点）。

    打包后（`sys.frozen`）取 exe 所在目录 —— 那是用户解压出来、会整个拷走的那一层，
    而不是 `_internal` 这种实现细节；未打包时取包根（= 仓库根）。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return _package_root()


def legacy_data_dir() -> str:
    """旧落点：`database` 现在**实际**放数据的地方（未外置时的程序目录）。

    刻意**不** import `database` 去读 `_REPO_ROOT`：那会把整条后端依赖（spacy 链路）
    拉起来，而 `start.py` 的「端口已占用 ⇒ 直接开浏览器」快路径本不该付这份代价。
    代价是两边各算一次目录 ⇒ 由测试钉住二者相等。
    """
    return _package_root()


def resolve_data_dir(env: Mapping[str, str]) -> str:
    """决定数据目录。优先级：① 显式 `DELECTOR_DATA_DIR` → ② 便携开关 → ③ 平台默认目录。"""
    explicit = env.get(DATA_DIR_ENV)
    if explicit:
        return explicit  # Android 注入 / 测试注入 / 运维显式指定：一律不覆盖
    if (env.get(PORTABLE_ENV) or "").strip().lower() in _PORTABLE_TRUE:
        return program_dir()
    if _is_windows():
        local = env.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
        return os.path.join(local, APP_DIR_NAME)
    home = env.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".local", "share", APP_DIR_NAME)


def _has_data(dir_path: str) -> bool:
    """该目录是否已有库文件（**存在**即算，不看 size —— 有库就不该再搬，避免覆盖）。"""
    return any(os.path.exists(os.path.join(dir_path, name)) for name in DB_FILE_NAMES)


def _db_files(legacy_dir: str) -> List[str]:
    """旧位置里真实存在的库文件（`isfile`：目录残留不算库，照 `preflight_data_dir` 的口径）。"""
    paths = [os.path.join(legacy_dir, name) for name in DB_FILE_NAMES]
    return [p for p in paths if os.path.isfile(p)]


def _try_checkpoint(db_path: str) -> bool:
    """把 `-wal` 里已提交的写入折回主库并截断 WAL；失败返回 False（由调用方退化为成套搬运）。"""
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
    except Exception as exc:
        _LOGGER.warning("无法打开 %s 做 checkpoint（%s）：改为连 -wal/-shm 一起搬。", db_path, exc)
        return False
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return True
    except Exception as exc:
        _LOGGER.warning("checkpoint %s 失败（%s）：改为连 -wal/-shm 一起搬。", db_path, exc)
        return False
    finally:
        conn.close()


def _wal_plan(sources: List[str], target_dir: str) -> List[Tuple[str, str]]:
    """checkpoint 之后 **-wal 仍非空** ⇒ 里面还有未落盘的数据，必须连 `-shm` 成套搬走。"""
    plan: List[Tuple[str, str]] = []
    for src in sources:
        wal = src + WAL_SUFFIX
        if not (os.path.isfile(wal) and os.path.getsize(wal) > 0):
            continue
        plan.append((wal, os.path.join(target_dir, os.path.basename(wal))))
        shm = src + SHM_SUFFIX
        if os.path.isfile(shm):
            plan.append((shm, os.path.join(target_dir, os.path.basename(shm))))
    return plan


def _rollback(paths: List[str]) -> None:
    """清理已复制到新位置的文件 —— 半套数据比没有数据危险得多（程序会拿它当真）。"""
    for path in paths:
        try:
            os.remove(path)
        except OSError as exc:
            _LOGGER.warning("回滚时删除 %s 失败：%s（请手动删除后再启动，否则会被当成真实数据）", path, exc)


def _retire_originals(sources: List[str]) -> None:
    """数据在新位置落稳**之后**，才把旧原件改名成 `*.bak-<时间戳>`（永不删除）。

    改名失败为什么是 **ERROR** 而不是 WARNING：此时新库已就位、旧库**保持原名**，两份
    同时在役；而上层「迁移未完成」提示因新位置**有**数据不会触发 ⇒ 这条日志是唯一线索。
    停在 WARNING 的话，旧文件会永久变成孤儿：用户以为数据已外置、放心地覆盖安装，实际
    那份原件才是他一直在写的库。
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for src in sources:
        try:
            os.replace(src, f"{src}.bak-{stamp}")
        except OSError as exc:
            _LOGGER.error(
                "旧库 %s 改名备份失败（%s）：数据已在新位置，旧文件**保持原名**——"
                "请手动把它复制走再删除，否则覆盖安装会丢掉这份原件。",
                src,
                exc,
            )


def migrate_legacy_data_dir(legacy_dir: str, target_dir: str) -> bool:
    """把旧位置的库搬到新位置。**返回 True 仅表示"本次确实搬了"**。

    前置条件（不满足即返回 False，一个字节都不写）：新位置还没有库文件、旧位置确有库文件、
    两者不是同一目录。任何异常 ⇒ 回滚新位置、旧位置**原封不动**、记 ERROR 日志并返回 False
    （No-Silent-Failure：绝不 `except: pass`，静默半搬比不搬危险得多）。
    """
    if os.path.normpath(os.path.abspath(legacy_dir)) == os.path.normpath(os.path.abspath(target_dir)):
        return False  # 同一目录：复制文件到自身会抛 SameFileError，且"搬"毫无意义
    if _has_data(target_dir):
        return False  # 新位置已有库：要么已迁移过，要么用户自己放的 —— 都不该覆盖
    sources = _db_files(legacy_dir)
    if not sources:
        return False  # 全新安装：没有旧数据可搬

    copied: List[str] = []
    try:
        os.makedirs(target_dir, exist_ok=True)
        for src in sources:
            _try_checkpoint(src)
        plan = [(src, os.path.join(target_dir, os.path.basename(src))) for src in sources]
        plan += _wal_plan(sources, target_dir)
        for src, dst in plan:
            shutil.copy2(src, dst)
            copied.append(dst)
    except Exception as exc:
        _LOGGER.error(
            "数据目录迁移失败（%s）：已回滚，旧位置 %s 未改动，新位置 %s 不留残骸。",
            exc,
            legacy_dir,
            target_dir,
            exc_info=True,
        )
        _rollback(copied)
        return False

    _retire_originals(sources)
    return True


def bootstrap_data_dir(env: MutableMapping[str, str], legacy_dir: Optional[str] = None) -> str:
    """决定落点 → 建目录 → 写回 `DELECTOR_DATA_DIR` → 迁移旧数据。**必须在 import server 之前跑**。

    返回最终落点；**空串表示"本次未接管"**（Android：落点由宿主注入，不由桌面逻辑猜）。

    两条失败策略（**只有一套**，不按失败点分叉）
    ------------------------------------------
    - 目录建不出来 / 迁移没落稳 ⇒ 回退旧落点并记 ERROR：起不来与静默空库都不可接受，两害
      相权取其轻 —— 至少保留旧行为，且错误信息明说"数据仍随程序目录"。（`makedirs` 成功但
      拷贝失败也算"没落稳"：那时新位置是个空且不可写的目录，env 指向它等于让用户用空库。）
    - **但调用方已显式设 `DELECTOR_DATA_DIR` 时一律不改写 env**（硬约束③在失败路径上同样
      成立）：那是用户 / Android 宿主表达"我要放这里"的唯一手段，悄悄换成别处比崩掉更不可
      接受 —— 此时只记 ERROR，由 `database` 建库时 fail-loud（看得见的失败 > 看不见的搬家）。
    """
    if is_android():
        return env.get(DATA_DIR_ENV, "")
    target = resolve_data_dir(env)
    was_explicit = env.get(DATA_DIR_ENV)  # 非空 ⇒ 落点是调用方选的，本函数只记录、不改写
    old = legacy_dir or legacy_data_dir()

    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        if was_explicit:
            _LOGGER.error(
                "显式指定的数据目录 %s 不可用（%s）：保留你的选择、不改写 env —— "
                "程序仍会在此处启动，若确实写不进去将由 database 明确报错。",
                target,
                exc,
            )
            return target
        _LOGGER.error(
            "数据目录 %s 不可用（%s）：回退到旧位置 %s —— 数据仍随程序目录，删除或覆盖它会丢数据。",
            target,
            exc,
            old,
        )
        env[DATA_DIR_ENV] = old
        return old

    env[DATA_DIR_ENV] = target
    if migrate_legacy_data_dir(old, target):
        _LOGGER.warning(
            "数据目录已迁移：%s → %s（旧文件保留为 *.bak-<时间戳>，确认无误后可自行删除）。",
            old,
            target,
        )
        return target

    if _has_data(old) and not _has_data(target):
        # 有旧数据却没落在新位置 ⇒ 迁移失败（或被挡住）。这是最危险的中间态：env 指向一个
        # 空目录，程序会当它是全新安装 ⇒ 与"目录建不出来"采取同一套回退，不再分叉。
        if was_explicit:
            _LOGGER.error(
                "数据迁移未完成：旧位置 %s 仍有库文件，而显式落点 %s 是空的 —— "
                "保留你的选择、不改写 env；照日志里的两个路径手动复制后再启动。",
                old,
                target,
            )
            return target
        _LOGGER.error(
            "数据迁移未完成（%s → %s）：回退到旧位置 %s —— 数据仍随程序目录，删除或覆盖它会丢数据。",
            old,
            target,
            old,
        )
        env[DATA_DIR_ENV] = old
        return old
    return target
