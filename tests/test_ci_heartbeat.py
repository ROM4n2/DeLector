# -*- coding: utf-8 -*-
"""``tools/ci_heartbeat.py`` 的可选硬截止语义。

为什么有这组用例
----------------
2026-11-04 的 Windows Portable Smoke 卡死最终由 job 级 30 分钟超时终止，结论
``cancelled``，与「被后续 push 顶掉」无法区分。包装器新增的 ``--deadline-seconds``
负责把脚本级卡死变成 ``124`` ⇒ 步骤 failure。本组用例钉住：

1. 不传截止时退出码原样透传（纯旁路纪律没被破坏）；
2. 传截止且子进程挂住时，到点杀树并返回 124；
3. 传截止但子进程正常结束时，不误杀、原样返回 0。

用例自身 MUST 有界：所有 ``subprocess.run`` 都带 ``timeout``，避免把测试进程也挂死。
"""

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL = REPO_ROOT / "tools" / "ci_heartbeat.py"


def _run(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    assert TOOL.exists(), f"心跳包装器不存在：{TOOL}"
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_exit_code_passthrough_without_deadline() -> None:
    """不传 --deadline-seconds：子进程退出码原样返回（纯旁路）。"""
    result = _run("--stage", "test", "--", sys.executable, "-c", "import sys; sys.exit(3)")
    assert result.returncode == 3, (
        f"未传截止时包装器改写了退出码：{result.returncode} != 3\n"
        f"stderr={result.stderr}"
    )


def test_deadline_kills_hang_and_returns_124() -> None:
    """子进程挂住时，硬截止必须杀树并返回 124（可识别的 failure）。"""
    started = time.monotonic()
    result = _run(
        "--stage",
        "test",
        "--deadline-seconds",
        "2",
        "--",
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
    )
    elapsed = time.monotonic() - started

    assert result.returncode == 124, (
        f"硬截止未生效：退出码 {result.returncode} != 124\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    output = result.stdout + result.stderr
    assert "deadline exceeded" in output, f"缺少截止判据日志：{output!r}"
    assert "rc=124" in output, f"缺少最终 rc=124 日志：{output!r}"
    assert elapsed < 20, f"截止后包装器没有及时退出：{elapsed:.1f}s"


def test_deadline_does_not_fire_for_fast_command() -> None:
    """子进程正常结束时，截止参数不得误杀或改写退出码。"""
    result = _run(
        "--stage",
        "test",
        "--deadline-seconds",
        "10",
        "--",
        sys.executable,
        "-c",
        "print('fast')",
    )
    assert result.returncode == 0, (
        f"正常命令被截止误杀或退出码被改写：{result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )


def test_non_positive_deadline_is_config_error() -> None:
    """非正数截止属于配置错误（argparse 退出码 2），不得静默当成无截止。"""
    result = _run(
        "--stage",
        "test",
        "--deadline-seconds",
        "0",
        "--",
        sys.executable,
        "-c",
        "print('should-not-run')",
    )
    assert result.returncode == 2, (
        f"--deadline-seconds 0 未被拒绝：退出码 {result.returncode}\n"
        f"stderr={result.stderr}"
    )
