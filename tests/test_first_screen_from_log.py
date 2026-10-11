# -*- coding: utf-8 -*-
"""`tools/first_screen_from_log.py` 的回归锁：用**造出来的假日志**钉解析逻辑。

纪律：绝不读用户真实 `launch.log`（内容 / 存在与否都不可控）—— 每条用例都在 `tmp_path` 写一份
**受控**的假日志，再跑脚本、断言输出与退出码。标记字符串必须与写方 desktop.py 同源，由本文件
`test_markers_match_desktop_writer` 另钉（任一侧改了字面量 ⇒ 漂移即红）。
"""

import ast
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


# ── Task 2：6 枚新启动标记不得让解析器抢错锚行（行为级 + 结构化守卫）──────────────
def _new_stage_markers_from_desktop() -> List[str]:
    """从 desktop.py 的 `_run_desktop_inner` **同源取** 6 枚启动阶段标记（AST 取 `_append_log` 的
    第二个字符串实参，按源码出现顺序）。

    为何同源取而不在本文件复制字面量：复制即**第二份真相源** —— desktop.py 一改标记，副本会
    **静默漂移**，这枚回归锁转而去守护一份过期字面量（正是本项目反复栽过的坑）。
    为何只取函数体**顶层**的 `_append_log`：成功路径的 6 枚标记都是顶层语句；失败分支里的日志
    （如「未检测到 WebView2 运行时…」）嵌在 `if` 内、不属于这 6 枚 —— 取顶层即可精确命中。
    """
    tree = ast.parse(DESKTOP.read_text(encoding="utf-8"))
    func = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_desktop_inner"
    )
    markers: List[str] = []
    for stmt in func.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
            continue
        call = stmt.value
        if not (isinstance(call.func, ast.Name) and call.func.id == "_append_log"):
            continue
        if len(call.args) >= 2:
            arg = call.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                markers.append(arg.value)
    return markers


def test_new_stage_markers_do_not_hijack_first_screen_parser(tmp_path: Path) -> None:
    """6 枚新启动标记**不得**让 `first_screen_from_log.py` 抢错锚行。

    解析器是**子串匹配**（`marker in line.message`）：只要新标记不含三条锚串，端到端三段的锚行
    就仍取自真锚。本用例用**真实（从 desktop.py 同源取）标记**造合成日志，端到端验证三段数字
    未被抢走 —— 一旦某枚新标记含锚串，锚点会先命中它、数字静默变味。
    """
    markers = _new_stage_markers_from_desktop()
    assert len(markers) == 6, (
        f"_run_desktop_inner 顶层应有 6 枚启动标记，实际 {len(markers)} 枚：{markers}"
        "（标记增删请同步本回归锁，勿让它静默守护过期清单）"
    )

    # 时间戳（秒级）与顺序严格照 desktop.py 的写入次序：起点=08、6 枚标记=08→11、splash=11、
    # 服务就绪=13、首屏=14 ⇒ 期望三段为 5s / 1s / 6s。
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:08", START + "。"),
            ("2026-10-10 12:00:08", markers[0]),
            ("2026-10-10 12:00:09", markers[1]),
            ("2026-10-10 12:00:09", markers[2]),
            ("2026-10-10 12:00:10", markers[3]),
            ("2026-10-10 12:00:10", markers[4]),
            ("2026-10-10 12:00:11", markers[5]),
            ("2026-10-10 12:00:11", "已创建 splash 窗口。"),
            ("2026-10-10 12:00:13", READY + "。"),
            ("2026-10-10 12:00:14", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    # 逐行断言（不是"含某个数字"）：三段都必须精确取自真锚行；任一新标记含锚串都会让此处对不上。
    out_lines = proc.stdout.splitlines()
    assert "起点 → 服务就绪: 5s" in out_lines, proc.stdout
    assert "服务就绪 → 首屏已加载: 1s" in out_lines, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 6s" in out_lines, proc.stdout


def test_new_stage_markers_do_not_contain_first_screen_anchor_substrings() -> None:
    """结构化防碰撞守卫（**解析器侧**）：6 枚新标记**各自都不得**把三条首屏锚串当子串。

    与 `tests/test_desktop_shell.py::test_stage_markers_do_not_contain_first_screen_anchor_substrings`
    呼应，但守在这里（解析器侧）：`first_screen_from_log.py` 的 `_last_index` / `_first_index_after`
    用 `marker in line.message` 做子串匹配 ⇒ 某枚新标记一旦含「开始启动（进程级计时起点）/
    服务已就绪 / 真实 UI 已加载（首屏可用）」，锚点会**先命中这枚新标记**、计时切片**抢错行**，
    端到端首屏数字**静默变味**（不报错，只是算成别的意思）。
    """
    markers = _new_stage_markers_from_desktop()
    assert len(markers) == 6, f"_run_desktop_inner 顶层应有 6 枚启动标记，实际 {len(markers)} 枚：{markers}"
    for marker in markers:
        for anchor in (START, READY, SCREEN):
            assert anchor not in marker, (
                f"新标记 {marker!r} 含首屏锚串 {anchor!r}：解析器会抢错行、端到端数字静默变味"
            )
