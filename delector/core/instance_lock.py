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
再改 env 也晚了。故这里只碰 `json` / `os` / `tempfile` / `dataclasses`。
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Mapping, Optional, Protocol

if TYPE_CHECKING:
    # Task 2 才引入真实的 LockHandle（持有锁 fd + release）；这里只声明 Task 1 用到的形状，
    # 让 mypy 能解析前向引用，同时不把运行期符号提前泄漏。
    class LockHandle(Protocol):
        paths: LockPaths

APP_DIR_NAME = "DeLector"
LOCK_FILE_NAME = "instance.lock"
META_FILE_NAME = "instance.json"


@dataclass(frozen=True)
class LockRecord:
    pid: int
    version: str
    port: int
    data_dir: str
    acquired_at: str


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


def write_record(handle: "LockHandle", record: LockRecord) -> None:
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
