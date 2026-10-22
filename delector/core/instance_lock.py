# -*- coding: utf-8 -*-
r"""桌面单实例锁的记录与元数据读写（spec 2026-10-21 §3.1）。

为什么锁与元数据分两个文件
--------------------------
POSIX 的 `flock` 锁的是 **inode** 而不是路径。若锁与元数据共用一个文件、每次回写都
`os.replace`，旧 fd 仍锁着已被 unlink 的旧 inode，下一个进程打开新 inode 就能成功加锁
—— 锁会**静默失效**。故 `instance.lock` 只做锁目标、内容可为空且永不替换；
`instance.json` 单独走临时文件 + `os.replace`，让读者永远看到完整 JSON。

为什么本模块顶层只 import stdlib
-------------------------------
`delector.database` 在导入时就把 `DATA_DIR` 落定；本模块会被 `start.py` 放在
`bootstrap_data_dir` 之前导入（spec §3.2），一旦间接拉起 `database`，bootstrap
再改 env 也晚了。故本模块的不变式是：**顶层只 import stdlib**（包名可增删，不必枚举）。
"""

from __future__ import annotations

import contextlib
import errno
import importlib
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from types import ModuleType
from typing import Mapping, Optional

APP_DIR_NAME = "DeLector"
LOCK_FILE_NAME = "instance.lock"
META_FILE_NAME = "instance.json"

#: 具名 logger 沿用仓库惯例（见 `data_dir_bootstrap`），日志总线是 `delector`。
_LOGGER = logging.getLogger("delector")

#: 平台原语导入失败只在**首次**降级时喊一次；否则每次启动都刷一条同样的 WARNING 会淹掉日志。
_PRIMITIVE_MISSING_WARNED = False

#: 这些 errno 才代表「别人已经持有锁」。其余 errno（`ENOLCK`/`EIO`/`ENOSPC`…）是原语或文件系统
#: 本身出问题，必须走降级（`None`）并留痕 —— 一律当成「被持有」会把 NFS/SMB 上的失败伪装成
#: 「已有实例在跑」，用户永远看不到 WARNING。Windows `msvcrt.locking` 的冲突码也是 `EACCES`。
_HELD_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK})


@dataclass(frozen=True)
class LockRecord:
    pid: int
    version: str
    port: int
    data_dir: str
    acquired_at: str


#: 读不出对方元数据时的占位记录：明确「有实例在跑，但身份未知」，绝不猜、绝不复用。
UNKNOWN_RECORD = LockRecord(pid=0, version="unknown", port=0, data_dir="", acquired_at="")


@dataclass(frozen=True)
class LockPaths:
    lock: str
    meta: str

    @staticmethod
    def for_platform(env: Mapping[str, str]) -> "LockPaths":
        """平台默认落点。**刻意不建目录**：建目录是调用方职责，纯函数才便于注入测试。"""
        local = env.get("LOCALAPPDATA")
        if local:
            # 显式 env 优先于 os.name：测试用 env 模拟另一平台，不能被跑测主机覆盖。
            base = os.path.join(local, APP_DIR_NAME)
        else:
            # env 里显式出现 XDG/HOME 说明调用方在模拟 POSIX（主机可能是 Windows），
            # 故 env 优先于 os.name；两边都没有才退回本机平台默认。
            xdg = env.get("XDG_DATA_HOME")
            home = env.get("HOME")
            if xdg:
                base = os.path.join(xdg, APP_DIR_NAME)
            elif home:
                base = os.path.join(home, ".local", "share", APP_DIR_NAME)
            elif os.name == "nt":
                base = os.path.join(os.path.expanduser("~/AppData/Local"), APP_DIR_NAME)
            else:
                base = os.path.join(os.path.expanduser("~"), ".local", "share", APP_DIR_NAME)
        return LockPaths(
            lock=os.path.join(base, LOCK_FILE_NAME),
            meta=os.path.join(base, META_FILE_NAME),
        )


@dataclass
class LockHandle:
    """已持有的锁句柄。

    为什么 `_fd` 必须全程保持打开
    ----------------------------
    锁的拥有者是这个 fd（Windows 句柄 / POSIX open file description），不是 record。
    一旦关闭，OS 立刻释放锁 —— 崩溃也同理（spec §4「进程被杀 ⇒ 锁自愈」），
    所以这里**不做 pid 探活**：pid 复用与「刚死未回收」都会骗人。
    """

    paths: LockPaths
    record: LockRecord
    _fd: int = -1

    @property
    def is_degraded(self) -> bool:
        """本次没有真互斥（原语缺失 / 目录不可建 / 文件打不开）：仍拿到句柄，但不是锁。"""
        return self._fd < 0

    def release(self) -> None:
        """幂等释放：关闭 fd（OS 随之解锁）。降级句柄（`_fd == -1`）为空操作。"""
        fd = self._fd
        # 先置 -1 再关闭：即使 os.close 抛异常，第二次 release 也不会对同一 fd 重复操作。
        self._fd = -1
        if fd < 0:
            return
        _close_fd(fd)


def read_record(paths: LockPaths) -> Optional[LockRecord]:
    """读元数据；缺失 / 非 JSON / 字段缺失或类型不对 ⇒ None（不把解析异常抛给启动主链）。"""
    try:
        # utf-8-sig：Windows 记事本等会写 BOM，带 BOM 的 JSON 会被 json 判成非法。
        with open(paths.meta, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        # JSONDecodeError 是 ValueError 子类；「文件不存在」与「半截 JSON」都收敛为版本未知。
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    version = data.get("version")
    port = data.get("port")
    data_dir = data.get("data_dir")
    acquired_at = data.get("acquired_at")
    # bool 是 int 的子类：`{"pid": true}` 不能被当成合法 pid。
    if not isinstance(pid, int) or isinstance(pid, bool):
        return None
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if not isinstance(version, str) or not isinstance(data_dir, str) or not isinstance(acquired_at, str):
        return None
    return LockRecord(pid=pid, version=version, port=port, data_dir=data_dir, acquired_at=acquired_at)


def write_record(handle: LockHandle, record: LockRecord) -> None:
    """原子回写元数据：临时文件写满 + `os.replace`，读者要么看到旧 JSON、要么看到新 JSON。"""
    paths = handle.paths
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=os.path.dirname(paths.meta),
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            tmp_path = tmp.name
            json.dump(asdict(record), tmp, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, paths.meta)
        tmp_path = ""
    finally:
        # 任何失败类型（含 TypeError）都要清掉半截临时文件；清理失败不得掩盖原始异常。
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


# ── 平台锁原语 ────────────────────────────────────────────────────────────────
#
# 为什么用 importlib 惰性导入而不是模块级 `if sys.platform: import msvcrt/fcntl`
# -------------------------------------------------------------------------
# 同一份源码要在两个平台上都通过 `mypy --strict`：Windows 的 typeshed 把 `fcntl` 声明成
# 空模块（无 flock / LOCK_EX），模块级导入会在本机报 attr-defined。惰性导入同时把
# 「原语不可用」变成可返回值（None），让降级显式、可测，而不是在导入期炸掉启动主链。
#
# 先例：本机另一代码库的 acquire_lock 是同一套三档结构 —— 非阻塞试锁 → 失败即读对方身份
# → 原语不可用则响亮降级。这里只借结构，实现全部基于 stdlib。


def _load_primitive(name: str) -> Optional[ModuleType]:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


def _warn_degraded(reason: str) -> None:
    """锁降级的唯一喇叭。文案必须点明「不是真互斥」，否则读日志的人会以为单实例仍成立。"""
    _LOGGER.warning("单实例锁降级（%s）：本次不是真互斥，同机多实例可能同时启动。", reason)


def _warn_missing_primitive_once() -> None:
    global _PRIMITIVE_MISSING_WARNED
    if _PRIMITIVE_MISSING_WARNED:
        return
    _PRIMITIVE_MISSING_WARNED = True
    _warn_degraded(f"平台 {sys.platform!r} 无可用的文件锁原语")


def _close_fd(fd: int) -> None:
    """关 fd 即解锁。关闭失败必须留痕：静默吞掉会让人误以为锁已释放。"""
    try:
        os.close(fd)
    except OSError as exc:
        _LOGGER.warning("关闭单实例锁 fd 失败（fd=%d）：%s", fd, exc)


def _acquire_windows_lock(fd: int) -> Optional[bool]:
    # 「原语缺失」的三个来源（模块、加锁函数、常量）统一在这里喊话：`try_acquire` 看到 `None`
    # 时无法区分「原语缺失」与「原语存在但加锁被拒」，兜底喊话会给出假陈述。
    msvcrt = _load_primitive("msvcrt")
    if msvcrt is None:
        _warn_missing_primitive_once()
        return None
    locking = getattr(msvcrt, "locking", None)
    # 常量同理属于原语：无默认值的 getattr 会让 AttributeError 穿出 try_acquire 并泄漏锁 fd。
    lock_nblck = getattr(msvcrt, "LK_NBLCK", None)
    if locking is None or lock_nblck is None:
        # 名字在模块里不存在属于_attribute_缺失而不是 OSError：必须降级，不能让它穿出去。
        _warn_missing_primitive_once()
        return None
    # 锁区间从文件头算起：不 seek 回去就会锁在 fd 上一次读写留下的位置。
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        locking(fd, lock_nblck, 1)
    except OSError as exc:
        if exc.errno in _HELD_ERRNOS:
            # 非阻塞加锁的冲突码 ⇒ 别人持有，这是判定结果而不是错误。
            return False
        _warn_degraded(f"Windows 加锁失败（errno={exc.errno}）：{exc}")
        return None
    return True


def _acquire_posix_lock(fd: int) -> Optional[bool]:
    # 同 Windows：模块 / 加锁函数 / 常量三种缺失都在这里喊话，`None` 只剩「原语不可用」一义。
    fcntl = _load_primitive("fcntl")
    if fcntl is None:
        _warn_missing_primitive_once()
        return None
    flock = getattr(fcntl, "flock", None)
    lock_ex = getattr(fcntl, "LOCK_EX", None)
    lock_nb = getattr(fcntl, "LOCK_NB", None)
    if flock is None or lock_ex is None or lock_nb is None:
        _warn_missing_primitive_once()
        return None
    try:
        flock(fd, lock_ex | lock_nb)
    except OSError as exc:
        if exc.errno in _HELD_ERRNOS:
            return False
        # 例：NFS/SMB 上 flock 返 ENOLCK —— 这是原语不可用，不是「已有实例在跑」。
        _warn_degraded(f"POSIX 加锁失败（errno={exc.errno}）：{exc}")
        return None
    return True


def _acquire_os_lock(fd: int) -> Optional[bool]:
    """True=拿到；False=被他人持有；None=本平台原语缺失（调用方降级，不阻断启动）。"""
    if sys.platform == "win32":
        return _acquire_windows_lock(fd)
    return _acquire_posix_lock(fd)


def _ensure_parent_dir(paths: LockPaths) -> bool:
    """`os.open` 打开的是 `paths.lock`、回写落在 `paths.meta`：两个父目录都要建。

    只建 meta 的父目录时，任意「lock 与 meta 不同目录」的 `LockPaths` 组合都会在 `os.open` 处
    降级；反过来只建 lock 的父目录则回写必失败。
    """
    parents = dict.fromkeys((os.path.dirname(paths.lock), os.path.dirname(paths.meta)))
    for parent in parents:
        if not parent:
            continue
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            _warn_degraded(f"无法创建锁目录 {parent}（{exc}）")
            return False
    return True


def try_acquire(paths: LockPaths, record: LockRecord) -> "LockHandle | LockRecord":
    """非阻塞取锁：拿到 ⇒ `LockHandle`；被持有 ⇒ 对方的 `LockRecord`（读不出 ⇒ `UNKNOWN_RECORD`）。

    为什么任何失败都返回句柄而不是抛
    ------------------------------
    锁是「防止两个实例同时改库」的加固层，不是启动的前置条件。目录不可建 / 文件打不开
    （只读介质、权限）时把用户挡在门外比降级更糟（spec §2.2 最后一行），故一律降级为
    无互斥句柄并 WARNING；调用方拿到 `LockHandle` 就继续启动，行为等于今天的端口探测路径。
    """
    if not _ensure_parent_dir(paths):
        return LockHandle(paths=paths, record=record, _fd=-1)

    try:
        fd = os.open(paths.lock, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        _warn_degraded(f"无法打开锁文件 {paths.lock}（{exc}）")
        return LockHandle(paths=paths, record=record, _fd=-1)

    acquired = _acquire_os_lock(fd)
    if acquired is None:
        # `None` 有两种来源：原语缺失（已在 `_acquire_*_lock` 里喊过）、原语存在但加锁被拒
        # （那里已打含真实 errno 的 WARNING）。此处再喊会给出假陈述，还会把
        # `_PRIMITIVE_MISSING_WARNED` 置真，让同进程后续真·原语缺失变成零 warning。
        _close_fd(fd)
        return LockHandle(paths=paths, record=record, _fd=-1)
    if not acquired:
        _close_fd(fd)
        # 锁被持有但 meta 缺失/半截是合法中间态：收敛为 unknown，绝不把 None 漏给调用方。
        return read_record(paths) or UNKNOWN_RECORD

    handle = LockHandle(paths=paths, record=record, _fd=fd)
    try:
        write_record(handle, record)
    except OSError as exc:
        # 锁已经拿到了：回写失败（Windows 上并发 read_record 会让 os.replace 抛 WinError 32）
        # 只影响「别人看到谁」，不影响互斥，故照样返回句柄继续启动，绝不把 fd 悬空抛出去。
        _warn_degraded(f"回写元数据失败（{exc}）：锁仍持有，对方身份可能读到旧值")
    except (TypeError, ValueError) as exc:
        # 记录本身不可序列化 = 调用方 bug：不吞（warn 显式点名），也不留悬空 fd。
        handle.release()
        _warn_degraded(f"锁记录无法序列化（{exc!r}）：已释放锁，本次不是真互斥")
        return LockHandle(paths=paths, record=record, _fd=-1)
    return handle
