# -*- coding: utf-8 -*-
"""Linux 受管布局与符号链接切换（`delector/core/update_linux.py`）。

符号链接通过注入的 ``symlink_fn`` 模拟（写一个记录目标的普通文件），
避免在 Windows 上依赖创建符号链接的权限。
"""

import tarfile
from pathlib import Path
from typing import Callable, List, Tuple

import pytest

from delector.core.update_linux import (
    apply_switch,
    extract_payload,
    link_path,
    managed_root,
    plan_switch,
    rollback,
)


def _fake_symlink(records: List[Tuple[str, Path]]) -> Callable[[str, Path], None]:
    def create(target: str, link: Path) -> None:
        records.append((target, Path(link)))
        Path(link).write_text(target, encoding="utf-8")

    return create


def _managed_exe(tmp_path: Path, version: str = "1.0.0") -> Path:
    exe = tmp_path / "versions" / version / "DeLector"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    return exe


def test_managed_root_and_link_follow_xdg(tmp_path: Path) -> None:
    env = {"XDG_DATA_HOME": str(tmp_path / "data"), "XDG_BIN_HOME": str(tmp_path / "bin")}

    assert managed_root(env) == tmp_path / "data" / "DeLector"
    assert link_path(env) == tmp_path / "bin" / "DeLector"


def test_plan_switch_rejects_unmanaged_layout(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere" / "DeLector"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("", encoding="utf-8")

    plan = plan_switch(tmp_path, elsewhere, "2.0.0", link=tmp_path / "bin" / "DeLector")

    assert plan is None


def test_plan_switch_points_to_new_version(tmp_path: Path) -> None:
    current = _managed_exe(tmp_path, "1.0.0")
    link = tmp_path / "bin" / "DeLector"

    plan = plan_switch(tmp_path, current, "2.0.0", link=link)

    assert plan is not None
    assert plan.version_dir == (tmp_path / "versions" / "2.0.0").resolve()
    assert plan.previous == (tmp_path / "versions" / "1.0.0").resolve()
    assert plan.link_path == link


def test_apply_switch_writes_through_temporary_link(tmp_path: Path) -> None:
    current = _managed_exe(tmp_path, "1.0.0")
    link = tmp_path / "bin" / "DeLector"
    plan = plan_switch(tmp_path, current, "2.0.0", link=link)
    assert plan is not None
    records: List[Tuple[str, Path]] = []

    apply_switch(plan, symlink_fn=_fake_symlink(records))

    assert records and records[0][0].endswith("DeLector")
    assert not (tmp_path / "bin" / "DeLector.new").exists()
    assert (tmp_path / "versions" / "1.0.0").is_dir()  # 旧版本保留用于回滚


def test_rollback_switches_to_previous_version(tmp_path: Path) -> None:
    current = _managed_exe(tmp_path, "1.0.0")
    link = tmp_path / "bin" / "DeLector"
    plan = plan_switch(tmp_path, current, "2.0.0", link=link)
    assert plan is not None
    records: List[Tuple[str, Path]] = []
    fake = _fake_symlink(records)

    apply_switch(plan, symlink_fn=fake)
    rollback(plan, symlink_fn=fake)

    assert records[-1][0].endswith(str(Path("versions") / "1.0.0" / "DeLector"))
    assert "1.0.0" in link.read_text(encoding="utf-8")


def test_extract_payload_rejects_escape(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        info = tarfile.TarInfo("../escape")
        info.size = 0
        handle.addfile(info)

    with pytest.raises(ValueError):
        extract_payload(archive, tmp_path / "versions" / "2.0.0")


def test_extract_payload_finds_binary(tmp_path: Path) -> None:
    payload = tmp_path / "ok"
    payload.mkdir()
    binary = payload / "DeLector"
    binary.write_text("", encoding="utf-8")
    archive = tmp_path / "ok.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(binary, arcname="DeLector-v2-Linux-x64/DeLector")

    root = extract_payload(archive, tmp_path / "versions" / "2.0.0")

    assert (root / "DeLector").is_file()
