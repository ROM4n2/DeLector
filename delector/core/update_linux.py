# -*- coding: utf-8 -*-
"""Linux 便携版的受管布局：版本目录 + 符号链接原子切换。

只是"能解压到任意目录"的升级版：先把安装收敛到
``${XDG_DATA_HOME:-~/.local/share}/DeLector/versions/<version>/``，再让
``${XDG_BIN_HOME:-~/.local/bin}/DeLector`` 指向它。切换用临时符号链接 + ``os.replace``，
旧版本目录保留一份用于回滚。

**不在受管布局内的运行一律拒绝自替换**（``plan_switch`` 返回 None）：用户把包解到桌面
时，任何"自动换目录"都只会制造第二个副本。
"""

import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

__all__ = [
    "SwitchPlan",
    "apply_switch",
    "extract_payload",
    "link_path",
    "managed_root",
    "plan_switch",
    "rollback",
]


@dataclass(frozen=True)
class SwitchPlan:
    version_dir: Path
    link_path: Path
    previous: Optional[Path]


def _env(env: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if env is None else env


def managed_root(env: Optional[Mapping[str, str]] = None) -> Path:
    values = _env(env)
    base = values.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "DeLector"


def link_path(env: Optional[Mapping[str, str]] = None) -> Path:
    values = _env(env)
    base = values.get("XDG_BIN_HOME") or str(Path.home() / ".local" / "bin")
    return Path(base) / "DeLector"


def plan_switch(
    root: Path,
    current_exe: Path,
    version: str,
    *,
    link: Optional[Path] = None,
) -> Optional[SwitchPlan]:
    """当前可执行文件不在 ``root/versions/`` 下时拒绝自替换。"""
    versions = (root / "versions").resolve()
    try:
        executable = current_exe.resolve()
    except OSError:
        return None
    if versions not in executable.parents:
        return None

    target_link = link if link is not None else link_path()
    previous = executable.parent
    version_dir = (versions / version).resolve()
    if version_dir == previous:
        return None
    return SwitchPlan(version_dir=version_dir, link_path=target_link, previous=previous)


def extract_payload(archive: Path, version_dir: Path) -> Path:
    """解压 tar.gz 到版本目录；拒绝逃逸条目，返回含 ``DeLector`` 的目录。"""
    version_dir = version_dir.resolve()
    version_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive, "r:gz") as handle:
        for member in handle.getmembers():
            target = (version_dir / member.name).resolve()
            if target != version_dir and version_dir not in target.parents:
                raise ValueError(f"归档条目逃逸版本目录: {member.name!r}")
        handle.extractall(version_dir)  # 逐条路径已校验，拒绝逃逸条目

    executable = next(iter(version_dir.rglob("DeLector")), None)
    if executable is None:
        raise ValueError("归档内缺少 DeLector 可执行文件")
    return executable.parent


def apply_switch(plan: SwitchPlan, *, symlink_fn: Callable[[str, Path], None] = os.symlink) -> None:
    """原子切换符号链接：先建临时链接，再 ``os.replace`` 覆盖旧链接。"""
    plan.link_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = plan.link_path.with_name(plan.link_path.name + ".new")
    temporary.unlink(missing_ok=True)
    symlink_fn(str(plan.version_dir / "DeLector"), temporary)
    os.replace(temporary, plan.link_path)


def rollback(plan: SwitchPlan, *, symlink_fn: Callable[[str, Path], None] = os.symlink) -> None:
    """切回上一版本目录；旧目录在切换时并未删除。"""
    if plan.previous is None:
        return
    apply_switch(
        SwitchPlan(version_dir=plan.previous, link_path=plan.link_path, previous=None),
        symlink_fn=symlink_fn,
    )
