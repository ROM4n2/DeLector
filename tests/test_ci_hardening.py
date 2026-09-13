# -*- coding: utf-8 -*-
"""CI 配置守卫测试（docs/plans/2026-09-09-ci-hardening.md Task 1，RED 阶段）。

在 `.github/workflows/ci.yml` 与 `.github/dependabot.yml` 尚不存在时，先钉死
它们的**最低契约**，让后续 Task 3 / Task 4 按 RED → GREEN 落地，并长期防止
"只在发版日才炸"的 CI 缺口回潮：

1. ci.yml 必须让 PR/push 即跑全量测试 + Go 三门禁（gofmt / vet / -race），
   门禁不能只挂在发版 workflow 里；
2. setup-go 的 `cache:` 参数是 boolean——写成 `cache: "go"` 会被 runner
   直接拒绝（99-Inbox 教训），本测试作为回归钉；
3. dependabot 必须覆盖 pip / github-actions / gomod 三个活跃生态并周更，
   依赖漂移要前置暴露，不能攒到打包日。

断言纪律（Vault AUTOMATION-GOTCHAS §5）：只用"关键要素子集"断言
（`'pytest' in text` 风格），**禁止 == 全文比对**——护栏要挡住契约倒退，
但不能冻结文件内容、阻挡正常演进。
"""

from pathlib import Path

import pytest

# 统一从本测试文件定位仓库根（tests/ 的上一级），不依赖 CWD
REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"


def _read_guard_file(path: Path) -> str:
    """读取被守护的配置文件；缺失时 fail，并给出可操作的提示信息。"""
    if not path.exists():
        pytest.fail(
            f"被守护的配置文件不存在：{path}\n"
            "它是本守卫测试钉下的 CI 契约对象；请按 "
            "docs/plans/2026-09-09-ci-hardening.md 的对应 Task 创建它，"
            "而不是删除或跳过本测试。"
        )
    return path.read_text(encoding="utf-8")


def test_ci_workflow_has_core_gates():
    """ci.yml 必须包含 PR/push 触发与全量测试 + Go 三门禁的关键要素。"""
    text = _read_guard_file(CI_WORKFLOW)

    # 每个要素都带一条"缺了意味着什么"的说明，失败时能直接定位契约缺口
    required_gates = [
        ("pull_request", "缺 pull_request 触发：PR 上不跑 CI，门禁形同虚设"),
        ("push", "缺 push 触发：master 被直推绕过门禁时无人拦截"),
        ("branches: [master]", "缺 branches: [master]：触发范围漂移，可能跑错分支或不跑"),
        ("pytest", "缺 pytest：Python 全量测试没进 CI 门禁"),
        ("gofmt -l", "缺 gofmt -l：Go 格式门禁没接上，清账成果会回潮"),
        ("go vet ./...", "缺 go vet：静态检查门禁缺失"),
        ("go test -race ./...", "缺 go test -race：Go 测试没进 CI，且丢了竞态检测"),
        ("concurrency", "缺 concurrency 取消组：同分支旧跑会与新跑并发执行"),
        ("cancel-in-progress", "缺 cancel-in-progress：旧提交的 CI 不会取消，反馈变慢"),
        ("setup-go@v5", "缺 actions/setup-go@v5：Go 工具链没安装，Go 门禁无法执行"),
    ]
    missing = [f"未找到 {needle!r}（{why}）" for needle, why in required_gates if needle not in text]
    assert not missing, f"{CI_WORKFLOW} 缺少关键门禁要素：\n" + "\n".join(missing)


def test_ci_setup_go_cache_is_boolean():
    """setup-go 的 cache 必须是 boolean（99-Inbox 陷阱回归钉）。

    setup-go@v5 的 `cache:` 只接受 boolean；写成 `cache: "go"` 会被 runner
    拒绝。正确写法是 `cache: true`（配 cache-dependency-path）。
    """
    text = _read_guard_file(CI_WORKFLOW)

    assert "cache: true" in text, (
        f"{CI_WORKFLOW} 的 setup-go 步骤缺少 `cache: true`：不显式开启会退回默认行为并拖慢 Go 构建。"
    )
    # 不做"排除所有带引号 cache"的宽泛断言：setup-python 合法地用 cache: "pip"，
    # 只钉 setup-go 这一具体陷阱
    bad_literal = 'cache: "go"'
    assert bad_literal not in text, (
        f"{CI_WORKFLOW} 出现了 setup-go 的字符串型 cache 写法："
        "setup-go 的 cache 参数是 boolean，字符串值会被 runner 直接拒绝"
        "（99-Inbox 教训），请改回 `cache: true`。"
    )


def test_dependabot_covers_active_ecosystems():
    """dependabot 必须覆盖 pip / github-actions / gomod 三生态，且周更。"""
    text = _read_guard_file(DEPENDABOT)

    assert "version: 2" in text, f"{DEPENDABOT} 缺少 `version: 2`：这是 dependabot 配置的必填版本头。"

    # 不引入 pyyaml：按行解析 package-ecosystem 的取值（容忍引号与行尾注释）
    ecosystems = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("package-ecosystem:"):
            value = stripped.split(":", 1)[1].split("#", 1)[0].strip().strip("\"'")
            ecosystems.add(value)
    required_ecosystems = {"pip", "github-actions", "gomod"}
    missing_ecosystems = required_ecosystems - ecosystems
    assert not missing_ecosystems, (
        f"{DEPENDABOT} 的 package-ecosystem 未覆盖活跃生态 "
        f"{sorted(missing_ecosystems)}，当前只声明了 {sorted(ecosystems)}。"
        "pip（Python 后端）/ github-actions（workflow 自身）/ gomod（agent/）"
        "三者的依赖漂移都必须前置暴露，不能攒到发版日。"
    )

    # 三个生态各需一个 weekly 调度：按 interval: 行的取值统计（同样容忍引号）
    weekly_count = sum(
        1
        for line in text.splitlines()
        if line.strip().startswith("interval:")
        and line.strip().split(":", 1)[1].split("#", 1)[0].strip().strip("\"'") == "weekly"
    )
    assert weekly_count >= 3, (
        f"{DEPENDABOT} 中 schedule.interval 为 weekly 的条目只有 "
        f"{weekly_count} 个：三个生态（pip / github-actions / gomod）"
        "都应各配置一条周更调度。"
    )
