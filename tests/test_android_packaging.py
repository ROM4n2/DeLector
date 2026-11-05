"""Android APK 打包完整性守卫（本地产物结构检查）。

CI 没有 Android 构建 job（``android-emulator.yml`` 仅 ``workflow_dispatch``），
缺 APK 时本文件的用例全部 skip，这是设计行为；本地需先跑
``assembleDeviceDebug`` / ``assembleEmulatorDebug`` 再跑本文件。

两类判据都是**结构**判据，不使用体积阈值：

1. 必需条目齐全且非空：emulator 必须含两个 ABI 的 ``libpython3.10.so`` 与三份
   ``requirements-*.imy``；单 ABI 的 device 包里 ``requirements-arm64-v8a.imy``
   允许是 EOCD-only 空包（依赖折入 ``requirements-common.imy``），其余仍须非空。
2. 本地头连续：按 ``header_offset`` 排序后，相邻条目之间不允许有空隙。这条用来抓
   "条目被重排后原位置留下死区"导致的膨胀包（体积看不出来，物理布局才看得出来）。
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APK_DEVICE = REPO_ROOT / "android/app/build/outputs/apk/device/debug/app-device-debug.apk"
APK_EMULATOR = REPO_ROOT / "android/app/build/outputs/apk/emulator/debug/app-emulator-debug.apk"

_LOCAL_HEADER_MAGIC = 0x04034B50
#: 空 ZIP 的唯一合法形态：EOCD（``PK\x05\x06``）+ 18 个零字节，共 22 B。
_EOCD_ONLY = b"PK\x05\x06" + b"\x00" * 18

_EMULATOR_REQUIRED = (
    "lib/arm64-v8a/libpython3.10.so",
    "lib/x86_64/libpython3.10.so",
    "assets/chaquopy/requirements-arm64-v8a.imy",
    "assets/chaquopy/requirements-common.imy",
    "assets/chaquopy/requirements-x86_64.imy",
)
_DEVICE_REQUIRED = (
    "lib/arm64-v8a/libpython3.10.so",
    "assets/chaquopy/requirements-arm64-v8a.imy",
    "assets/chaquopy/requirements-common.imy",
)
_DEVICE_EMPTY_ALLOWED = frozenset({"assets/chaquopy/requirements-arm64-v8a.imy"})


def _skip_if_missing(apk: Path, build_task: str) -> None:
    if not apk.exists():
        pytest.skip(f"{apk} 不存在：需先运行 {build_task}（CI 无 Android 构建 job，故跳过属设计行为）")


@pytest.mark.parametrize(
    ("apk", "required", "empty_allowed", "build_task"),
    [
        (APK_DEVICE, _DEVICE_REQUIRED, _DEVICE_EMPTY_ALLOWED, "assembleDeviceDebug"),
        (APK_EMULATOR, _EMULATOR_REQUIRED, frozenset(), "assembleEmulatorDebug"),
    ],
    ids=["device", "emulator"],
)
def test_required_entries_present_and_non_empty(
    apk: Path,
    required: tuple[str, ...],
    empty_allowed: frozenset[str],
    build_task: str,
) -> None:
    """必需条目必须存在；除允许的空包外，内容不得为 0 B 或 EOCD-only 空 ZIP。"""
    _skip_if_missing(apk, build_task)

    with zipfile.ZipFile(apk) as zf:
        present = set(zf.namelist())
        missing = [name for name in required if name not in present]
        assert not missing, f"{apk.name} 缺少必需条目：\n" + "\n".join(missing)

        empty = []
        for name in required:
            if name in empty_allowed:
                continue
            data = zf.read(name)
            if len(data) == 0 or (name.endswith(".imy") and data == _EOCD_ONLY):
                empty.append(name)
        assert not empty, f"{apk.name} 的必需条目为空（0 B 或 EOCD-only）：\n" + "\n".join(empty)

        for name in empty_allowed:
            data = zf.read(name)
            assert data == _EOCD_ONLY, (
                f"{apk.name} 的 {name} 允许为空，但必须是 EOCD-only（22 B），实际 {len(data)} B"
            )


def _local_data_start(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> int:
    """按本地头里的实际 name/extra 长度计算条目数据起点。"""
    fp = zf.fp
    assert fp is not None
    fp.seek(info.header_offset)
    magic = struct.unpack("<I", fp.read(4))[0]
    assert magic == _LOCAL_HEADER_MAGIC, (
        f"{info.filename} 的本地头不是 PK\\x03\\x04（offset={info.header_offset}）"
    )
    fp.seek(info.header_offset + 26)
    name_len, extra_len = struct.unpack("<HH", fp.read(4))
    return info.header_offset + 30 + name_len + extra_len


@pytest.mark.parametrize(
    ("apk", "build_task"),
    [
        (APK_DEVICE, "assembleDeviceDebug"),
        (APK_EMULATOR, "assembleEmulatorDebug"),
    ],
    ids=["device", "emulator"],
)
def test_local_headers_are_contiguous(apk: Path, build_task: str) -> None:
    """相邻条目的本地头必须紧邻，出现空隙即判为膨胀/死区。"""
    _skip_if_missing(apk, build_task)

    with zipfile.ZipFile(apk) as zf:
        infos = sorted(zf.infolist(), key=lambda info: info.header_offset)
        gaps = []
        for prev, nxt in zip(infos, infos[1:]):
            expected = _local_data_start(zf, prev) + prev.compress_size
            if nxt.header_offset != expected:
                gaps.append(
                    f"「{prev.filename}」之后 expected={expected}，"
                    f"下一条目「{nxt.filename}」offset={nxt.header_offset}，"
                    f"空隙 {nxt.header_offset - expected} B"
                )
        assert not gaps, f"{apk.name} 本地头不连续（{len(gaps)} 处死区/膨胀）：\n" + "\n".join(gaps)
