"""Android 启动就绪轮询策略守卫。

为什么是「纯 Java + javac 直跑」而不是 Robolectric：同 `tests/test_android_webview_policy.py`
——本仓没有 androidx.test / Robolectric 依赖，CI 的 pytest 矩阵只装 Python/Node；把轮询
节奏抽成零 Android 依赖的 `StartupReadinessPolicy` 后，用 javac 就能做真行为断言。

守三件事：
1. 节奏本身：前 50 次 120 ms、之后 600 ms，总预算 36 s（与改造前 60×600 对齐）。
2. MainActivity 真的接入了策略，而不是继续留字面量（否则策略测试全绿也没意义）。
3. 端口交接与 fatalError 早退的既有语义没被顺手改掉。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "android" / "app"
MAIN = APP / "src" / "main" / "java" / "org" / "delector" / "app" / "MainActivity.java"
POLICY = APP / "src" / "main" / "java" / "org" / "delector" / "app" / "StartupReadinessPolicy.java"
POLICY_TEST = (
    APP / "src" / "test" / "java" / "org" / "delector" / "app" / "StartupReadinessPolicyTest.java"
)

EXPECTED_CHECKS = 13


def _main_source() -> str:
    assert MAIN.is_file(), f"缺少 {MAIN}"
    return MAIN.read_text(encoding="utf-8")


def _poll_method_body() -> str:
    src = _main_source()
    assert "private void pollServerReadiness" in src, "缺少 pollServerReadiness"
    # 方法体到下一个同级私有方法为止（保持与文件既有缩进一致）
    return src.split("private void pollServerReadiness")[1].split("\n    private ")[0]


def test_policy_has_no_android_or_androidx_imports():
    text = POLICY.read_text(encoding="utf-8")
    imports = re.findall(r"^import\s+([\w.]+)\s*;", text, re.M)
    offenders = [i for i in imports if i.startswith("android.") or i.startswith("androidx.")]
    assert not offenders, f"StartupReadinessPolicy 必须零 Android 依赖，实际引入了: {offenders}"


def test_main_activity_uses_policy_instead_of_literals():
    body = _poll_method_body()
    assert "StartupReadinessPolicy.maxAttempts()" in body, (
        "pollServerReadiness 必须用 StartupReadinessPolicy.maxAttempts() 决定轮询上限"
    )
    assert "StartupReadinessPolicy.pollIntervalMs(" in body, (
        "pollServerReadiness 必须用 StartupReadinessPolicy.pollIntervalMs(...) 决定等待间隔"
    )
    assert "StartupReadinessPolicy.isReadyStatus(" in body, (
        "pollServerReadiness 必须用 StartupReadinessPolicy.isReadyStatus(...) 判定就绪"
    )
    assert "Thread.sleep(600)" not in body, "旧的 600ms 字面量仍在：轮询节奏没有真正接入策略"
    assert not re.search(r"for\s*\(\s*int\s+i\s*=\s*0\s*;\s*i\s*<\s*60\s*;", body), (
        "旧的 60 次字面量仍在：轮询上限没有接入策略"
    )


def test_poll_preserves_port_and_fatal_semantics():
    """收紧节奏不得改变端口真相来源，也不得让超时文案盖掉 Python 的真实错误。"""
    body = _poll_method_body()
    assert "readServerPort(dataDir)" in body, "端口必须继续只从 Python 写下的端口文件读取"
    assert "serverBaseUrl(serverPort) + \"/api/settings\"" in body, (
        "就绪探测仍应打 /api/settings，且地址由 serverBaseUrl(serverPort) 拼装"
    )
    assert "if (fatalError != null)" in body, "缺少 fatalError 早退：超时文案会覆盖真实错误"


def test_policy_behaviour_with_javac(tmp_path: Path):
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.skip("javac/java 不在 PATH 上；策略行为断言无法执行（静态断言仍然生效）")

    classes = tmp_path / "classes"
    classes.mkdir()

    compiled = subprocess.run(
        [javac, "-encoding", "UTF-8", "-d", str(classes), str(POLICY), str(POLICY_TEST)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert compiled.returncode == 0, f"javac 编译失败:\n{compiled.stdout}\n{compiled.stderr}"

    run = subprocess.run(
        [java, "-cp", str(classes), "org.delector.app.StartupReadinessPolicyTest"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    output = (run.stdout or "") + (run.stderr or "")
    assert run.returncode == 0, f"StartupReadinessPolicyTest 失败（exit={run.returncode}）:\n{output}"
    assert "FAIL " not in output, f"存在失败用例:\n{output}"
    assert f"checks={EXPECTED_CHECKS} failed=0" in output, (
        f"用例数不是 {EXPECTED_CHECKS}（可能被删改）:\n{output}"
    )
