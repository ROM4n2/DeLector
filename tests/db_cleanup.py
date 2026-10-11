# -*- coding: utf-8 -*-
"""测试库清理 helper：确定性删除 SQLite 库文件三件套，删失败**绝不允许静默吞掉**。

背景（2026-10 事故）：17 个 ``clean_db`` fixture 各自复制粘贴
``for f in (...): try: os.remove except OSError: pass``——Windows 上句柄未 close
时 ``os.remove`` 抛 ``PermissionError``（OSError 子类），被吞 = 残留库/残留行跨
用例污染（既造假红也造假绿：``tests/test_server.py`` 单跑 5 failed、逐条隔离
复跑真实红只有 3 条，多出的 2 条就是前一个失败用例的库文件删不掉所致）。

本模块是那 17 份复制粘贴的唯一实现：``remove_db_files(*paths)`` 把每个主库路径
展开为三件套（``path`` / ``path-wal`` / ``path-shm``），删不掉就 gc + 有限次重试，
最终仍失败 ⇒ 抛出点名根因与修法的异常。单测：``tests/test_db_cleanup_helper.py``。
"""

import gc
import os
import time
from typing import Dict, Mapping

# 首删 1 次 + 至多 _RETRY_LIMIT 次重试；每次失败后 gc.collect() 断
# sqlite3.Connection 内部 statement 缓存的引用环 + 短 sleep 给句柄释放留时间。
_RETRY_LIMIT = 3
_RETRY_SLEEP_SECONDS = 0.1

_FAIL_HINT = (
    "十有八九是 sqlite3.Connection 未 close（Windows 上句柄未释放时 os.remove 抛 "
    "PermissionError）。残留库/残留行会跨用例污染（假红/假绿），绝不允许静默吞掉。"
    "修法：把 `with get_db(...) as conn:` 换成 `with db_conn(...)`（progress 库用 "
    "`with db_progress_conn(...)`），或在 finally 里用 _close_db_conn(conn) 显式关闭。"
)


def remove_db_files(*paths: str) -> None:
    """确定性删除 SQLite 库文件三件套（path / path-wal / path-shm）。

    删失败**绝不允许静默吞掉**：Windows 上句柄未 close 时 os.remove 抛
    PermissionError（OSError 子类），吞掉它 = 残留行跨用例污染（假红/假绿）。
    策略：gc.collect() + 有限次重试（短 sleep）；最终仍失败 ⇒ 抛出**指明根因
    与修法**的异常（句柄未 close ⇒ 残留污染；修法 = 用 db_conn/db_progress_conn
    或 _close_db_conn 显式关闭）。

    幂等：文件不存在 ⇒ 跳过、不抛。
    """
    for base in paths:
        for suffix in ("", "-wal", "-shm"):
            target = base + suffix
            if not os.path.exists(target):
                continue  # 幂等：文件不存在 ⇒ 跳过、不抛
            attempts = 0
            while True:
                try:
                    os.remove(target)
                    break
                except OSError as exc:
                    attempts += 1
                    if attempts > _RETRY_LIMIT:
                        # 消息刻意不含重试次数：无论重试上限怎么调，同一根因抛出
                        # 的消息逐字一致（变异验证依赖这一点）。
                        raise OSError(
                            f"remove_db_files: 无法删除 {target!r}（有限次重试后仍失败）。"
                            f"{_FAIL_HINT} 原始异常：{exc!r}"
                        ) from exc
                    gc.collect()  # 断 sqlite3.Connection 引用环，给句柄释放机会
                    time.sleep(_RETRY_SLEEP_SECONDS)


# ── 仓库根「数据目录」快照（`tests/conftest.py` 的会话守卫用）────────────────────
# 缺陷现场（2026-10-11）：仓库根出现一套**新的** delector.db / progress.db，随后
# `tests/test_save_wb_state_cost.py` 的迁移闸拒绝运行 ⇒ **本地 2 红、CI 全绿**。
# 机制：`database.DATA_DIR` 在 `DELECTOR_DATA_DIR` 缺席时兜底仓库根（database.py:36），而
# `delector/server.py` 在**模块顶层**就 `init_db()` ⇒ 「没先钉落点就 import server」= 建库。
ROOT_DB_NAMES = ("delector.db", "progress.db")


def root_db_snapshot(root: str) -> Dict[str, int]:
    """仓库根那两套库（含 `-wal` / `-shm` 侧文件）的快照：文件名 → 字节数。"""
    snapshot: Dict[str, int] = {}
    for name in ROOT_DB_NAMES:
        for suffix in ("", "-wal", "-shm"):
            path = os.path.join(root, f"{name}{suffix}")
            if os.path.isfile(path):
                snapshot[f"{name}{suffix}"] = os.path.getsize(path)
    return snapshot


def describe_root_db_diff(before: Mapping[str, int], after: Mapping[str, int]) -> str:
    """把两次快照的差异说成人话（新出现 / 被改动 / 消失），供守卫报错用。"""
    added = sorted(set(after) - set(before))
    changed = sorted(name for name in set(after) & set(before) if after[name] != before[name])
    removed = sorted(set(before) - set(after))
    parts = []
    if added:
        parts.append(f"新出现：{', '.join(added)}")
    if changed:
        parts.append(f"被改动：{', '.join(changed)}")
    if removed:
        parts.append(f"消失：{', '.join(removed)}")
    return "；".join(parts) if parts else "无差异"
