# -*- coding: utf-8 -*-
"""发布侧真启闸的超时 / 心跳接线守卫（2026-11-13 整体健康度审计 P1 #3）。

事故形态（CONFIRMED via skeptic read）：`ci.yml:354-373` 已接双重护栏
（`ci_heartbeat.py --deadline-seconds 480` + 步骤级 `timeout-minutes: 10`），
但 `build-release.yml` 的构建 / 验包两步仍是裸命令、`build-agent.yml` 全文
无超时 —— 发布侧挂死只被 job 级超时记成 `cancelled`，与「被顶掉」同形。

判据是**结构化 YAML 解析**（`yaml.safe_load` 后按 job / step 取真值），
不是字符串在场断言：后者挡不住「把 timeout 挪到别的 step」或「心跳只写在注释里」。
"""

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE = REPO_ROOT / ".github" / "workflows" / "build-release.yml"
AGENT = REPO_ROOT / ".github" / "workflows" / "build-agent.yml"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step(job: dict[str, Any], name_needle: str) -> dict[str, Any]:
    for step in job.get("steps", []):
        if name_needle in str(step.get("name", "")):
            return step
    raise AssertionError(f"job 里找不到步骤 {name_needle!r}（真删了，不是挪了位置）")


def test_release_verify_step_has_hard_deadline_and_step_timeout() -> None:
    """发布侧验包步 MUST 与 CI 侧同一套双重护栏。"""
    verify = _step(_load(RELEASE)["jobs"]["build-windows"], "Verify Windows Portable")
    assert verify.get("timeout-minutes") == 10, (
        f"验包步缺步骤级 timeout-minutes: 10（实际 {verify.get('timeout-minutes')!r}）"
    )
    import re  # 局部 import：不为一条正则改动文件头 import 区

    run = str(verify.get("run", ""))
    # 判据 MUST 钉「同一条命令里的包裹关系」：把心跳与真启拆成两行独立命令时，
    # 子串在场断言照样全绿，但硬截止只罩住秒退的心跳行（独立 reviewer MAJOR）。
    assert re.search(
        r"ci_heartbeat\.py[^\n]*--deadline-seconds 480[^\n]*--[ \t]+python tools/verify_windows_portable\.py",
        run,
    ), "心跳与真启脚本必须在同一条命令里（用 `--` 包裹），否则挂死仍只记 cancelled"

    # 参照护栏在 ci.yml 的 Windows 冒烟 job 里；按步骤名遍历所有 job 找，
    # 不硬编码 job 名（paths-filter 与冒烟是两个 job，写死名字会守错对象）。
    ci_verify: dict[str, Any] | None = None
    for job in _load(CI)["jobs"].values():
        for step in job.get("steps", []):
            if "Verify Windows Portable" in str(step.get("name", "")):
                ci_verify = step
                break
        if ci_verify is not None:
            break
    assert ci_verify is not None, "ci.yml 里的参照护栏不见了（发布侧无从对齐）"
    assert ci_verify.get("timeout-minutes") == verify.get("timeout-minutes")
    assert re.search(
        r"--deadline-seconds 480[^\n]*--[ \t]+python tools/verify_windows_portable\.py",
        str(ci_verify.get("run", "")),
    ), "CI 侧参照护栏的包裹关系不成立"


def test_release_build_step_has_heartbeat() -> None:
    """构建步也要留相位证据（挂死时能分辨卡在 build 还是 verify）。"""
    import re

    build = _step(_load(RELEASE)["jobs"]["build-windows"], "Build Windows Portable")
    run = str(build.get("run", ""))
    assert re.search(
        r"ci_heartbeat\.py[^\n]*--stage build[^\n]*--[ \t]+python package_windows\.py",
        run,
    ), f"心跳与构建命令必须在同一条命令里，实际：{run!r}"


def test_build_agent_job_has_explicit_timeout() -> None:
    """build-agent.yml 三平台矩阵 MUST 有显式 job 级硬上限。"""
    job = _load(AGENT)["jobs"]["build-agent"]
    timeout = job.get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 60, (
        f"build-agent job 缺合理硬上限（实际 {timeout!r}）：挂死会烧满默认 360 分钟"
    )
def _auto_body_warning_violations(body: str) -> list[str]:
    """自动 Release 正文的失败版本警示判定器：缺任一要素都列为违规。

    判据落在**警示行本身**，不是整篇正文：v5.23.1 / v5.23.2 在后续正文里还会被
    提到（「v5.23.1 全平台白屏…」），只搜全文会让「警示行的版本号被删」假绿
    （实测变异自证抓到的漏洞）。
    """
    violations: list[str] = []
    warning_line = next((ln for ln in body.splitlines() if "请勿使用" in ln), "")
    if not warning_line:
        return ["自动正文没有明确的禁用措辞（整段警示缺失）"]
    # 只判「禁用措辞 + 版本列表」那一段（全角冒号前）：同一行的后文还会复述
    # 「v5.23.1 全平台白屏…」，按整行判会把「标题里的版本号被删」洗成绿。
    ban_list = warning_line.split("：", 1)[0]
    if "v5.23.1" not in ban_list or "v5.23.2" not in ban_list:
        violations.append("警示行的禁用版本列表未同时点名 v5.23.1 / v5.23.2")
    if "gh release edit" not in body or "另行核对" not in body:
        violations.append("自动正文未声明人工覆盖后需另行核对（不得声称已覆盖）")
    return violations


def test_release_auto_body_warns_about_broken_tags() -> None:
    """结构化 YAML 取 with.body 真值 → 判定器裁决；三类删改都必须变红。"""
    release = _load(RELEASE)["jobs"]["publish-github-release"]
    step = _step(release, "Create or Update Release")
    body = str(step.get("with", {}).get("body", ""))
    assert body, "Create or Update Release 缺 body（整体删除会静默无警示）"
    assert _auto_body_warning_violations(body) == [], _auto_body_warning_violations(body)

    assert _auto_body_warning_violations(body.replace("v5.23.1 / v5.23.2", "v5.23.0")), (
        "删掉废弃版本号却没变红"
    )
    assert _auto_body_warning_violations(body.replace("另行核对", "已覆盖")), (
        "把人工覆盖写成已覆盖却没变红"
    )
    line = next(ln for ln in body.splitlines() if "请勿使用" in ln)
    assert _auto_body_warning_violations(body.replace(line, "")), "整段警示被删却没变红"
