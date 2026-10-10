# -*- coding: utf-8 -*-
"""`tools/first_screen_from_log.py` 的回归锁：用**造出来的假日志**钉解析逻辑。

纪律：绝不读用户真实 `launch.log`（内容 / 存在与否都不可控）—— 每条用例都在 `tmp_path` 写一份
**受控**的假日志，再跑脚本、断言输出与退出码。标记字符串必须与写方 desktop.py 同源，由本文件
`test_markers_match_desktop_writer` 另钉（任一侧改了字面量 ⇒ 漂移即红）。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "first_screen_from_log.py"
DESKTOP = ROOT / "desktop.py"

# 与 desktop.py / first_screen_from_log.py 逐字对齐的三枚标记。
START = "开始启动（进程级计时起点）"
READY = "服务已就绪"
SCREEN = "真实 UI 已加载（首屏可用）"


def _write_log(path: Path, rows: List[Tuple[str, str]]) -> Path:
    path.write_text("".join(f"[{ts}] {msg}\n" for ts, msg in rows), encoding="utf-8")
    return path


def _run(log_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log_path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_markers_match_desktop_writer() -> None:
    """解析器与写日志方（desktop.py）的标记必须**同源**：任一侧改了字面量 ⇒ 本用例转红。"""
    src = DESKTOP.read_text(encoding="utf-8")
    for marker in (START, READY, SCREEN):
        assert marker in src, f"desktop.py 未写入标记「{marker}」：解析器与写方已漂移"


def test_computes_the_three_duration_rows(tmp_path: Path) -> None:
    """正常三行 ⇒ 三段差值都要算对（起点→就绪 3s、就绪→首屏 2s、端到端 5s）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:03", READY + "。"),
            ("2026-10-10 12:00:05", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert "起点 → 服务就绪: 3s" in proc.stdout, proc.stdout
    assert "服务就绪 → 首屏已加载: 2s" in proc.stdout, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 5s" in proc.stdout, proc.stdout


def test_uses_the_last_launch_as_the_epoch(tmp_path: Path) -> None:
    """日志是追加写：必须取**最后一次**启动为计时起点（否则会把上一轮的空档算进来）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 11:00:00", START + "。"),
            ("2026-10-10 11:00:10", READY + "。"),
            ("2026-10-10 11:00:20", SCREEN + "。"),
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:04", READY + "。"),
            ("2026-10-10 12:00:07", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert "起点 → 服务就绪: 4s" in proc.stdout, proc.stdout
    assert "服务就绪 → 首屏已加载: 3s" in proc.stdout, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 7s" in proc.stdout, proc.stdout


def test_missing_loaded_line_is_reported_not_guessed(tmp_path: Path) -> None:
    """缺 `loaded` 行（旧日志）⇒ 明确报"不含首屏事件"，**不得**静默给 0（故非零退出）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:03", READY + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode != 0, "缺 loaded 行必须非零退出（不得静默给 0）"
    assert "不含首屏事件" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_garbled_log_fails_with_plain_language(tmp_path: Path) -> None:
    """日志存在但格式乱 ⇒ 人话失败、非零退出，**不得**抛栈崩掉。"""
    log = tmp_path / "launch.log"
    log.write_text("\x00\x01 这不是日志\n随机内容\n仍不是\n", encoding="utf-8")
    proc = _run(log)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "Traceback" not in combined, f"格式乱也必须人话失败、不得抛栈：{combined}"
    assert combined.strip(), "必须给出人话原因"


def test_missing_file_exits_nonzero_with_reason(tmp_path: Path) -> None:
    """找不到日志文件 ⇒ 非零退出 + 人话原因（并提示 --log 覆盖路径）。"""
    proc = _run(tmp_path / "nope.log")
    assert proc.returncode != 0
    assert "找不到" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
