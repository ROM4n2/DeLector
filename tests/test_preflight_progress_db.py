# -*- coding: utf-8 -*-
"""数据目录迁移闸必须**逐库**判定（2026-11-13 整体健康度审计 P1 #2）。

事故链（CONFIRMED via skeptic read）：`preflight_data_dir` 只判 `delector.db`；
显式 `DELECTOR_DATA_DIR=/new` 且新位置已有非空 `delector.db` 时提前 `return`，
旧位置的 `progress.db` 不搬也不报 ⇒ `init_db()` 在新位置重建**空进度库**，
`study_log` / `quiz_log` / `daily_summary` / `exam_trials` 全空且零提示。

判据是行为探针：真在临时目录造两个库文件、真调只读闸，不 mock 文件系统。
"""

from pathlib import Path

import pytest

from delector.core.db.connection import preflight_data_dir

_DB_BYTES = b"SQLite format 3\x00legacy rows"


def test_preflight_rejects_when_only_progress_db_is_left_behind(tmp_path: Path) -> None:
    """新位置有主库、缺 progress.db，旧位置两者俱全 ⇒ MUST 响亮拒启。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "delector.db").write_bytes(_DB_BYTES)
    (repo / "progress.db").write_bytes(_DB_BYTES)

    data = tmp_path / "data"
    data.mkdir()
    (data / "delector.db").write_bytes(_DB_BYTES)
    assert not (data / "progress.db").exists(), "前置：新位置必须缺 progress.db"

    with pytest.raises(RuntimeError) as excinfo:
        preflight_data_dir(str(data), str(repo))

    message = str(excinfo.value)
    assert "progress.db" in message, f"报错必须点名缺的是哪张库，实际：{message}"
    assert "cp " in message, "报错必须给出可直接复制的 cp 命令"
    assert "检测到数据目录迁移未完成" in message, "fail-loud 判定语被改掉了"


def test_preflight_allows_when_both_databases_are_present(tmp_path: Path) -> None:
    """反向钉子：两个库都在新位置 ⇒ 不得误报（旧位置仍在也不拦）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "delector.db").write_bytes(_DB_BYTES)
    (repo / "progress.db").write_bytes(_DB_BYTES)

    data = tmp_path / "data"
    data.mkdir()
    (data / "delector.db").write_bytes(_DB_BYTES)
    (data / "progress.db").write_bytes(_DB_BYTES)

    preflight_data_dir(str(data), str(repo))  # 不抛即通过


def test_preflight_allows_fresh_install_with_no_legacy_progress_db(tmp_path: Path) -> None:
    """反向钉子：旧位置没有 progress.db 的全新安装 ⇒ 不得因新库缺席而拦启动。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    (data / "delector.db").write_bytes(_DB_BYTES)

    preflight_data_dir(str(data), str(repo))  # 不抛即通过


def test_preflight_db_manifest_matches_bootstrap_manifest() -> None:
    """清单同步守卫：两份库名清单 MUST 同一套（现读真对象，不手抄）。

    connection.py 是 db/ 最底层切片、顶层只依赖标准库，不能反向 import
    data_dir_bootstrap；故这里用集合相等把「新增第三个库却只改一处」钉死。
    """
    from delector.core import data_dir_bootstrap
    from delector.core.db import connection

    assert set(connection.PREFLIGHT_DB_NAMES) == set(data_dir_bootstrap.DB_FILE_NAMES), (
        "数据目录迁移闸的库清单与 bootstrap 搬运清单漂移了："
        "少判一张库 = 又一条静默空库路径"
    )
