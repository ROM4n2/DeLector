# -*- coding: utf-8 -*-
"""T6：`requirements.lock.txt` 可解性机械闸的结构化接线判据 + 变异自证。

判据走 PyYAML 结构化解析（按 job / step 取真值），不是对整份 workflow 做
字符串在场断言 —— 后者挡不住「`--dry-run` 只写在注释里」或「步骤挪到别的 job」。
判定逻辑抽成纯函数 :func:`evaluate`，只吃 workflow 文本，阴性用例可注入最小文本。
"""

import re
import textwrap
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB_NAME = "static-invariants"
LOCK_FILE = "requirements.lock.txt"
STEP_NAME = "Verify requirements.lock.txt is solvable"


def _hits(doc: Any) -> list[tuple[str, dict[str, Any]]]:
    """结构化遍历：返回所有「run 里真的引用 lock 文件」的 (job 名, step)。"""
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for name, job in jobs.items():
        if isinstance(job, dict) and isinstance(job.get("steps"), list):
            for step in job["steps"]:
                if isinstance(step, dict) and LOCK_FILE in str(step.get("run", "")):
                    out.append((str(name), step))
    return out


def evaluate(workflow_text: str) -> list[str]:
    """返回违规理由清单；空列表 = 接线合规。纯函数，不读磁盘、不依赖 cwd。"""
    try:
        doc = yaml.safe_load(workflow_text)
    except yaml.YAMLError as exc:
        return [f"workflow 不是可解析 YAML：{exc}"]
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict) or not isinstance(jobs.get(JOB_NAME), dict):
        return [f"缺 {JOB_NAME} job：求解闸必须挂在该 job 内"]

    hits = _hits(doc)
    if not hits:
        return [f"没有任何 step 在 run 里引用 {LOCK_FILE}（求解闸被删）"]

    problems: list[str] = []
    if len(hits) > 1:
        problems.append(f"有 {len(hits)} 个 step 引用 {LOCK_FILE}（重复接线，判据失去唯一锚点）")
    for job_name, _step in hits:
        if job_name != JOB_NAME:
            problems.append(f"求解闸挂在 {job_name!r} job，MUST 挂在 {JOB_NAME!r} 内")
    owned = [step for job_name, step in hits if job_name == JOB_NAME]
    if not owned:
        return problems + [f"{JOB_NAME} 内没有求解闸 step"]

    step = owned[0]
    if STEP_NAME not in str(step.get("name", "")):
        problems.append(f"step 名称不含 {STEP_NAME!r}")
    run = str(step.get("run", ""))
    if "--dry-run" not in run:
        problems.append("run 缺 --dry-run：pip 会真装依赖，不是求解闸")
    if "--ignore-installed" not in run:
        problems.append("run 缺 --ignore-installed：runner 预装包会掩盖不可解组合")
    if not re.search(r"(?:python3?\s+-m\s+pip|pip)\s+install\b", run):
        problems.append("run 不是 pip install（真求解）")
    if "continue-on-error" in step:
        problems.append("step 声明了 continue-on-error：求解失败不红，闸形同虚设")
    timeout = step.get("timeout-minutes")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not (0 < timeout <= 60):
        problems.append(f"step 缺合理 timeout-minutes 上限（实际 {timeout!r}）")
    else:
        job_timeout = jobs[JOB_NAME].get("timeout-minutes")
        if isinstance(job_timeout, int) and not isinstance(job_timeout, bool) and timeout > job_timeout:
            problems.append(f"step 上限 {timeout} 超过 job 上限 {job_timeout}：步骤级护栏永不生效")
    return problems


def test_real_ci_workflow_passes_gate() -> None:
    """真实 ci.yml 必须绿；任何接线漂移都会让本用例红。"""
    assert evaluate(CI_WORKFLOW.read_text(encoding="utf-8")) == []


MINIMAL_WITHOUT_GATE = textwrap.dedent(
    """\
    name: CI
    jobs:
      static-invariants:
        timeout-minutes: 2
        steps:
          - name: Enforce docs layout criteria
            run: python3 tools/check_docs_layout.py
    """
)


def test_deleting_gate_step_is_red() -> None:
    """删掉求解闸的最小 workflow ⇒ 判定函数 MUST 报违规（只证明能绿等于没证明闸存在）。"""
    assert evaluate(MINIMAL_WITHOUT_GATE), "删掉求解闸后判定函数仍判绿：守卫失效"


def _mutate(text: str, fn: Callable[[Any], None]) -> str:
    """结构化变异：解析 → 改 dict → dump 回文本（不是字符串替换）。"""
    doc = yaml.safe_load(text)
    fn(doc)
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def _gate(doc: Any) -> dict[str, Any]:
    return next(
        s for s in doc["jobs"][JOB_NAME]["steps"] if LOCK_FILE in str(s.get("run", ""))
    )


def _drop_dry_run(doc: Any) -> None:
    _gate(doc)["run"] = _gate(doc)["run"].replace(" --dry-run", "")


def _add_tolerance(doc: Any) -> None:
    _gate(doc)["continue-on-error"] = True


def _drop_timeout(doc: Any) -> None:
    _gate(doc).pop("timeout-minutes", None)


@pytest.mark.parametrize(
    ("fn", "needle"),
    [
        pytest.param(_drop_dry_run, "dry-run", id="no-dry-run"),
        pytest.param(_add_tolerance, "continue-on-error", id="tolerant"),
        pytest.param(_drop_timeout, "timeout-minutes", id="no-timeout"),
    ],
)
def test_mutations_are_red(fn: Callable[[Any], None], needle: str) -> None:
    """把真 ci.yml 结构化改坏 ⇒ 判定函数 MUST 报违规，且理由指向被改坏的那一项。"""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    reasons = evaluate(_mutate(text, fn))
    assert reasons, f"变异 {fn.__name__} 后判定函数仍判绿 ⇒ 守卫失效"
    assert any(needle in reason for reason in reasons), reasons


def test_baseline_green_after_same_parser_roundtrip() -> None:
    """阳性对照：真 ci.yml 经同一 dump 往返后仍绿，排除「变异红是解析器假象」。"""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert evaluate(_mutate(text, lambda _doc: None)) == []
