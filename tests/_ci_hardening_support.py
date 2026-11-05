# -*- coding: utf-8 -*-
"""CI hardening 守卫的共享辅助（按主题拆分时抽出，函数体逐字节保持不变）。"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
ROOT_CONFTEST = REPO_ROOT / "conftest.py"
COST_GUARD_SHARDS = ("cost-guards", "cost-cold-start")
ANDROID_APP_BUILD_GRADLE = REPO_ROOT / "android" / "app" / "build.gradle"

def _read_guard_file(path: Path) -> str:
    """读取被守护的配置文件；缺失时 fail，并给出可操作的提示信息。"""
    if not path.exists():
        pytest.fail(
            f"被守护的配置文件不存在：{path}\n"
            "它是本守卫测试钉下的 CI 契约对象；请按 "
            "docs/plans/archive/2026-09-09-ci-hardening.md 的对应 Task 创建它，"
            "而不是删除或跳过本测试。"
        )
    return path.read_text(encoding="utf-8")

def _job_block(workflow: Path, job_name: str) -> str:
    """截出某个 workflow 文件里 jobs.<job_name> 的 YAML 文本块。

    不引 pyyaml（它不在 requirements.txt，是 CI 内单独装的开发期工具）：按两空格缩进的同级键
    切分，只取"这个 job 自己"的内容 —— 别的 job 出现同一字符串不算数，比全文搜索更严。
    """
    text = _read_guard_file(workflow)
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == f"  {job_name}:")
    except StopIteration:
        pytest.fail(f"{workflow} 找不到 jobs.{job_name}（两空格缩进的 `{job_name}:` 键）")

    end = len(lines)
    for i in range(start + 1, len(lines)):
        # 下一个同级 job / 顶层键：缩进回到两空格且以 "- " 之外的内容开头
        if lines[i].startswith("  ") and not lines[i].startswith("    ") and lines[i].strip():
            end = i
            break
    return "\n".join(lines[start:end])

def _ci_job_block(job_name: str) -> str:
    """截出 ci.yml 里某个 job 的 YAML 块（按两空格缩进的同级键切分）。

    不引 pyyaml（它不在 requirements.txt，是 CI 内单独装的开发期工具）：
    这里只需要"这个 job 自己的字段"，按缩进层级切比全文搜索更严 ——
    别的 job 写了 timeout-minutes 不算数，得是 `ci` 这个 job 自己有。
    """
    return _job_block(CI_WORKFLOW, job_name)

def _ci_step_blocks() -> dict[str, str]:
    """把 ci job 的 steps 按 `- name:` 切成 {步骤名: 块文本}。"""
    block = _ci_job_block("ci").replace("\r\n", "\n")
    chunks = re.split(r"\n      - name: ", block)
    steps: dict[str, str] = {}
    for chunk in chunks[1:]:
        steps[chunk.splitlines()[0].strip()] = chunk
    return steps

def _steps_of(job_block: str) -> list[str]:
    """把一个 job 块按 `      - ` 切分成各 step 的文本块。

    step 以 6 空格加 `- ` 起头（job 键两空格 + 其后字段再缩进四空格 + 连字符）。多行
    `run: |` 的正文缩进更深（10 空格），不会被误当作新 step。仅用于把「某一步自己的
    写法」与别步隔开，不解析 YAML（沿用本文件既有的按缩进切文本手法）。
    """
    lines = job_block.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"^ {6}- ", line)]
    blocks: list[str] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    return blocks

def _step_using(job_block: str, needle: str) -> str:
    """返回 job 块里第一条包含 needle 的 step 文本；找不到即 fail。"""
    matches = [step for step in _steps_of(job_block) if needle in step]
    assert matches, f"{CI_WORKFLOW} 的某个 job 内找不到包含 {needle!r} 的 step：\n{job_block}"
    return matches[0]
