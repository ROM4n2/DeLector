# -*- coding: utf-8 -*-
"""setup-go 判据：真 `uses:` 值，不靠注释里的旧版本号（审计报告 P2 #2 ①）。

旧判据 `"setup-go@v5" in text` 只命中 ci.yml 的注释（真实 action 已是 @v7），
是恒真死测。这里把「解析 YAML 后遍历 job/step 的 uses:」抽成纯函数，
阴性用例可注入最小文本。
"""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def setup_go_refs(workflow_text: str) -> list[str]:
    """只取真实 `uses:` 键的值；注释行、说明文字一概不算。"""
    jobs = yaml.safe_load(workflow_text).get("jobs") or {}
    refs: list[str] = []
    for job in jobs.values():
        if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
            continue
        for step in job["steps"]:
            if isinstance(step, dict) and str(step.get("uses", "")).startswith(
                "actions/setup-go@"
            ):
                refs.append(str(step["uses"]))
    return refs


def violations(workflow_text: str) -> list[str]:
    """返回违规理由；空列表 = 合规。"""
    refs = setup_go_refs(workflow_text)
    if not refs:
        return ["ci.yml 没有 setup-go 步骤的真实 uses: 声明（Go 门禁无法执行）"]
    problems: list[str] = []
    if len(set(refs)) != 1:
        problems.append(f"setup-go 版本不一致：{refs}（升级时漏改一处）")
    for ref in refs:
        if not re.fullmatch(r"actions/setup-go@v\d+", ref):
            problems.append(f"uses 值不合法：{ref!r}")
    return problems


def test_real_ci_uses_one_valid_setup_go_version() -> None:
    assert violations(CI_WORKFLOW.read_text(encoding="utf-8")) == []


def test_comment_only_mention_does_not_satisfy_guard() -> None:
    """旧子串判据在此假绿：注释里有 setup-go@v5，但没有真实 uses:。"""
    fake = (
        "#   setup-go@v5 的 cache 参数是 boolean，MUST 写 cache: true\n"
        "jobs:\n  ci:\n    steps:\n      - uses: actions/checkout@v7\n"
    )
    assert "setup-go@v5" in fake, "构造前提：注释里确实有旧判据依赖的子串"
    assert setup_go_refs(fake) == [], "注释被当成真实 uses: 值"
    assert violations(fake), "无真实 setup-go uses 时守卫必须报问题（不能恒真）"


def test_real_uses_removed_is_red() -> None:
    """注入式变异：删掉真实 uses ⇒ 守卫必红（锚点计数自证）。"""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert setup_go_refs(text), "前置：真 ci.yml 本来就有 setup-go uses"
    mutated = re.sub(
        r"(^\s*uses:\s*)actions/setup-go@\S+",
        r"\1actions/checkout@v7",
        text,
        flags=re.MULTILINE,
    )
    assert setup_go_refs(mutated) == [], "变异未生效（真实 uses 仍残留）"
    assert violations(mutated), "删掉真实 uses 后守卫仍全绿 ⇒ 死测"
