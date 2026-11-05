# -*- coding: utf-8 -*-
"""CI 工作流核心门禁：触发、go cache、dependabot、Ruff / Mypy、静态检查去重与容器入口。"""

import re

from _ci_hardening_support import (
    CI_WORKFLOW,
    DEPENDABOT,
    REPO_ROOT,
    _ci_job_block,
    _ci_step_blocks,
    _job_block,
    _read_guard_file,
)


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


# ── Ruff 静态门禁（2026-09-13 ruff-cleanup）────────────────────────────────────
# 背景：仓库此前零 lint 配置（CI Hardening 显式登记的已知边界）。本轮清账
# 2265→0 告警并接进 CI；下面两条把"门禁在"与"配置没被削弱"钉死。

RUFF_CONFIG = REPO_ROOT / "ruff.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"


def test_ci_workflow_has_ruff_gate():
    """ci.yml 必须把 Ruff lint 接进 PR/push 门禁（否则清账成果会回潮）。"""
    text = _read_guard_file(CI_WORKFLOW)

    required_gates = [
        (
            "pip install ruff",
            "缺 ruff 安装步骤：CI 里装不上 ruff，门禁无法执行"
            "（ruff 是开发期工具，不进 requirements.txt，须在 CI 内单独装）",
        ),
        (
            "ruff check",
            "缺 ruff check：Python lint 门禁没接上，delector/tests 的清账成果会静默回潮",
        ),
    ]
    missing = [f"未找到 {needle!r}（{why}）" for needle, why in required_gates if needle not in text]
    assert not missing, f"{CI_WORKFLOW} 缺少 Ruff 门禁要素：\n" + "\n".join(missing)


def test_ruff_config_locks_core_rules_and_stays_out_of_runtime_deps():
    """ruff.toml 必须存在且规则集/豁免面未被削弱；ruff 不得混入运行时依赖。"""
    text = _read_guard_file(RUFF_CONFIG)

    assert "line-length" in text, (
        "ruff.toml 缺 line-length：行宽约束丢失（2026-09-13 基线按存量分布定为 120）"
    )
    # 起步规则集逐条钉死（AUTOMATION-GOTCHAS §5：新增项逐条钉死，不做冻结集合断言）
    for rule in ('"E"', '"F"', '"I"'):
        assert rule in text, f"ruff.toml 的 select 缺 {rule}：起步规则集被削弱"

    assert '"delector/data/*.py"' in text, (
        "ruff.toml 缺 delector/data/*.py 的 E501 豁免声明："
        "数据字典的长行（单行一条数据）会重新变成告警噪音，而拆行会伤害 diff 稳定性"
    )

    req = _read_guard_file(REQUIREMENTS)
    assert "ruff" not in req, (
        "requirements.txt 不得包含 ruff：它是开发期工具，混入运行时依赖会增大"
        "Android 打包面体积与依赖漂移面（ci.yml 内单独 pip install 即可）"
    )


# ── Mypy 类型门禁（2026-09-13 mypy-cleanup）────────────────────────────────────
# 背景：仓库此前零类型检查配置。本轮以「适度严格档」清账全仓 138 → 0（check_untyped_defs
# 等四开关，见 pyproject.toml [tool.mypy] 的档位决策注释）；--strict（约 600 处
# no-untyped-def）递延另立。

MYPY_CONFIG = REPO_ROOT / "pyproject.toml"


def test_ci_workflow_has_mypy_gate():
    """ci.yml 必须把 Mypy 类型检查接进 PR/push 门禁（否则类型债静默回潮）。"""
    text = _read_guard_file(CI_WORKFLOW)

    required_gates = [
        (
            "pip install mypy",
            "缺 mypy 安装步骤：CI 里装不上 mypy（开发期工具，不进 requirements.txt，CI 内单独装）",
        ),
        (
            "mypy",
            "缺 mypy 调用：Python 类型检查门禁没接上，types/ 清账成果会静默回潮",
        ),
    ]
    missing = [f"未找到 {needle!r}（{why}）" for needle, why in required_gates if needle not in text]
    assert not missing, f"{CI_WORKFLOW} 缺少 Mypy 门禁要素：\n" + "\n".join(missing)


def test_desktop_entry_mypy_gate_pins_windows_platform():
    """桌面入口的 mypy 门禁 MUST 带 `--platform win32`（防"顺手删掉"⇒ Linux CI 必红）。

    为什么这条断言必须存在：`desktop.py` 是本项目 **Windows 专属**入口，源码用
    `ctypes.windll` 与 `winreg.*`；mypy **默认按运行平台**挑 typeshed，CI（ubuntu）下这两个
    模块没有 windll / OpenKey / KEY_READ / QueryValueEx / CloseKey 等属性 ⇒ 报 5 处
    attr-defined。即：不带 `--platform win32` 时同一条门禁"本地 Windows 绿、CI Linux 红"
    —— 结果是**平台的函数，不是代码的函数**（2026-10-10 该门禁第一次上线即因此红）。
    `--platform win32` 正是让它与目标平台一致的那味药，MUST NOT 删。
    """
    text = _read_guard_file(CI_WORKFLOW)

    # 定位桌面入口门禁命令：同时含 mypy 与三个目标文件的那一行（避免撞上说明性注释）。
    gate_lines = [
        line
        for line in text.splitlines()
        if "mypy" in line and "desktop.py" in line and "package_windows.py" in line and "conftest.py" in line
    ]
    assert gate_lines, (
        f"{CI_WORKFLOW} 找不到桌面入口的 mypy 门禁命令"
        "（应含 `mypy ... desktop.py package_windows.py conftest.py`）：门禁被删或改了目标面。"
    )
    for line in gate_lines:
        assert "--platform win32" in line, (
            f"{CI_WORKFLOW} 的桌面入口 mypy 门禁缺 `--platform win32`：\n"
            f"    {line.strip()}\n"
            "desktop.py 是 Windows 专属入口（ctypes.windll / winreg.*），不带该 flag 时 mypy 按 "
            "Linux typeshed 解析 ⇒ 报 5 处 attr-defined，CI（ubuntu）必红（本地 Windows 绿）。"
            "这条 flag 是门禁与目标平台一致的前提，MUST NOT 删。"
        )


def test_desktop_entry_mypy_gate_includes_start_entry() -> None:
    """桌面入口 mypy 门禁 MUST 覆盖 `start.py`（防日后被单独摘除后类型债盲区回潮）。

    为什么单列一条：上一条只钉那条命令的 `--platform win32`，**不钉目标文件清单**；若有人把
    `start.py` 从那行删掉，门禁依旧"在场"却**不再覆盖启动入口**—— 而 start.py 正是 ADR-0021
    点名的"最真实的类型债盲区"（长期无类型门禁）。故对它单点固化。
    """
    text = _read_guard_file(CI_WORKFLOW)

    # 与上一条同款定位：同含 mypy 与三个既有目标文件的那一行（避开说明性注释）。
    gate_lines = [
        line
        for line in text.splitlines()
        if "mypy" in line
        and "desktop.py" in line
        and "package_windows.py" in line
        and "conftest.py" in line
    ]
    assert gate_lines, (
        f"{CI_WORKFLOW} 找不到桌面入口的 mypy 门禁命令"
        "（应含 `mypy ... desktop.py package_windows.py conftest.py start.py`）：门禁被删或改了目标面。"
    )
    missing = [line.strip() for line in gate_lines if "start.py" not in line]
    assert not missing, (
        f"{CI_WORKFLOW} 的桌面入口 mypy 门禁未覆盖 start.py：\n  " + "\n  ".join(missing) + "\n"
        "start.py 是启动入口，长期无类型门禁（ADR-0021 点名的类型债盲区）；"
        "2026-10 去掉其两处 `# type: ignore` 后已并入本条，MUST NOT 被单独摘除。"
    )


# ── 静态检查去重守卫（2026-11-04，TODO-CI-01）──────────────────────────────────
# 背景：Ruff/mypy 六步原先在 matrix 公共 steps 里，六个 pytest 分片各装各跑一遍；
# 实测累计 92s、单份约 15s，属纯重复。2026-11 收敛为只在一个分片执行。
# 下面这条钉住"仍然只有一份、宿主分片仍在矩阵里、六个步骤都带同一条件"：
# 防止后续有人把静态检查复制回公共 steps（重复成本会静默回归），
# 也防止宿主分片改名/删除后条件恒假、检查静默消失（死绿比慢更坏）。

STATIC_GATE_STEP_NAMES = (
    "Install Ruff",
    "Ruff lint gate",
    "Install Mypy",
    "Mypy type gate (strict)",
    "Mypy type gate (tests, config baseline)",
    "Mypy type gate (desktop entry surface, strict)",
)


def test_static_gates_run_in_exactly_one_shard():
    """Ruff/mypy 六步必须只在一份分片执行，且宿主分片真实存在于 matrix。"""
    steps = _ci_step_blocks()
    shards: set[str] = set()

    for name in STATIC_GATE_STEP_NAMES:
        assert name in steps, (
            f"{CI_WORKFLOW} 缺少静态检查步骤 {name!r}：真实检查被删，不得用提速名义砍掉"
        )
        match = re.search(
            r"^\s*if:\s*matrix\.suite\.name\s*==\s*'([^']+)'\s*$",
            steps[name],
            re.MULTILINE,
        )
        assert match, (
            f"{name!r} 没有 `if: matrix.suite.name == '<分片>'` 守卫："
            "静态检查会重新落到六个分片各跑一遍（实测六份累计 92s，单份约 15s）"
        )
        shards.add(match.group(1))

    assert len(shards) == 1, f"六个静态步骤必须挂同一个分片，实际: {sorted(shards)}"

    shard = next(iter(shards))
    matrix_names = re.findall(r"^\s*- name:\s*(\S+)\s*$", _ci_job_block("ci"), re.MULTILINE)
    assert shard in matrix_names, (
        f"静态检查宿主分片 {shard!r} 不在 matrix 里（现有: {matrix_names}）："
        "条件永远为假，Ruff/mypy 会静默不跑（死绿比慢更坏）"
    )


# ── 纯 stdlib 机械闸合并守卫（2026-11-05，TODO-CI-04）─────────────────────────
# 背景：silent-degradation / mock-drift / layer-invariants 三个 job 各只跑一个秒级
# 判定器，却各占一台 runner、各付一次 checkout + setup-python（实测 job 11–13s，
# 其中判定器本身 1–3s）。
# ci-speed-budget §3.3 明确要求「只为一个断言单开 job」应并入现有机械闸；本轮
# 为抵消 cost 分片拆分新增的 1 个 job（峰值并发预算 ≤13），把它们合并成一个 job。
# 守卫钉住：三个判定器仍逐步执行、无 continue-on-error、job 级超时仍按轻量闸预算。
MECHANICAL_STDLIB_GATE_SCRIPTS = (
    "tools/check_silent_degradation.py",
    "tools/check_mock_drift.py",
    "tools/check_layer_invariants.py",
)
MECHANICAL_GATES_JOB = "static-invariants"


def test_mechanical_stdlib_gates_run_in_one_job() -> None:
    """三个纯 stdlib 判定器必须合并在一个 job 内逐步执行，且不得容错。"""
    text = _read_guard_file(CI_WORKFLOW)
    block = _job_block(CI_WORKFLOW, MECHANICAL_GATES_JOB)

    for script in MECHANICAL_STDLIB_GATE_SCRIPTS:
        run_line = f"run: python3 {script}"
        assert text.count(run_line) == 1, (
            f"`{run_line}` 在 {CI_WORKFLOW} 出现 {text.count(run_line)} 次："
            "合并后必须恰好接线一次（重复接线 = 白烧 runner；零次 = 检查被删）"
        )
        assert run_line in block, (
            f"{MECHANICAL_GATES_JOB} 缺 `{run_line}`：真实检查被删，不得用提速名义砍掉"
        )

    assert "continue-on-error" not in block, (
        f"{MECHANICAL_GATES_JOB} 声明了 continue-on-error：命中也不红，闸形同虚设"
    )

    match = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", block, re.MULTILINE)
    assert match, f"{MECHANICAL_GATES_JOB} 没有 timeout-minutes（会退回 360 分钟默认值）"
    assert 0 < int(match.group(1)) <= 2, (
        f"{MECHANICAL_GATES_JOB} 的 timeout-minutes = {match.group(1)}："
        "轻量机械闸预算为 2 分钟（三个脚本实测 3/1/1s，job 含 checkout+setup 11–13s），"
        "超过即为无意义等待"
    )


def test_mypy_config_locks_adoption_flags_and_stays_out_of_runtime_deps():
    """[tool.mypy] 必须锁住档位关键项；mypy 不得混入运行时依赖。"""
    text = _read_guard_file(MYPY_CONFIG)

    assert "[tool.mypy]" in text, f"{MYPY_CONFIG} 缺 [tool.mypy] 配置表"

    # 档位关键项逐条钉死（AUTOMATION-GOTCHAS §5：逐条钉死，不做冻结集合断言）
    required_flags = [
        ("check_untyped_defs = true", "未注解函数体检查是本档位的核心价值（默认档完全不查）"),
        ("no_implicit_optional = true", "隐式 Optional 已被 PEP 484 演进弃用"),
        ("warn_unused_ignores = true", "自净机制：多余的 type: ignore 会被报错，防清账退化成到处 ignore"),
        ("warn_redundant_casts = true", "冗余 cast 会掩盖真实类型错误"),
        ("ignore_missing_imports = true", "spaCy 等第三方无 stub，不忽略则噪音 import 错误淹没真实问题"),
    ]
    missing = [
        f"缺 {needle!r}（{why}）"
        for needle, why in required_flags
        if needle not in text.replace(" ", " ")
    ]
    assert not missing, f"{MYPY_CONFIG} 的 [tool.mypy] 档位被削弱：\n" + "\n".join(missing)

    req = _read_guard_file(REQUIREMENTS)
    assert "mypy" not in req, (
        "requirements.txt 不得包含 mypy：它是开发期工具，混入运行时依赖会增大"
        "Android 打包面体积与依赖漂移面（ci.yml 内单独 pip install 即可）"
    )


# ── 容器入口守卫（2026-09-28 swarm 审计 P1）────────────────────────────────────
# 背景：Dockerfile 的 CMD 曾写 `uvicorn server:app`，而仓库根并无 server.py
# （真实入口是 delector.server:app）——`docker compose up` 直接 ModuleNotFoundError。
# 本守卫静态钉住"入口模块文件存在 + 属性在模块级定义"，不触发 spaCy/lexicon 重导入。

DOCKERFILE = REPO_ROOT / "Dockerfile"


def test_dockerfile_uvicorn_entrypoint_points_to_real_module():
    """Dockerfile 的 uvicorn 入口必须指向真实存在的模块与模块级属性。"""
    text = _read_guard_file(DOCKERFILE)

    m = re.search(r'"uvicorn"\s*,\s*"([\w.]+):(\w+)"', text)
    assert m, (
        f"{DOCKERFILE} 未找到 `uvicorn <module>:<attr>` 形式的 CMD 入口：容器入口无法被本守卫校验。"
    )
    module, attr = m.group(1), m.group(2)

    module_file = REPO_ROOT.joinpath(*module.split(".")).with_suffix(".py")
    assert module_file.exists(), (
        f"Dockerfile CMD 指向的模块不存在：{module}:{attr} → 期望文件 {module_file} 缺失。"
        "真实入口通常是 delector.server:app（仓库根并无 server.py）。"
    )
    src = module_file.read_text(encoding="utf-8")
    assert re.search(rf"^{re.escape(attr)}\s*=", src, re.MULTILINE), (
        f"{module_file} 未在模块级定义 `{attr}`：Dockerfile CMD 期望 {module}:{attr} 可被 uvicorn 加载。"
    )
