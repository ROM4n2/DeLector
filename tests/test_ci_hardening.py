# -*- coding: utf-8 -*-
"""CI 配置守卫测试（docs/plans/archive/2026-09-09-ci-hardening.md Task 1，RED 阶段）。

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

import ast
import re
from pathlib import Path

import pytest

# 统一从本测试文件定位仓库根（tests/ 的上一级），不依赖 CWD
REPO_ROOT = Path(__file__).resolve().parents[1]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
ROOT_CONFTEST = REPO_ROOT / "conftest.py"


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


# ── Android Python 运行时契约（pydantic v1 兼容；2026-09-28 swarm 审计 P1）────────
# 背景：Android 打包面走 Chaquopy，只能装纯 Python 依赖 ⇒ 锁 `pydantic<2.0.0`
# （v2 的 pydantic-core 是 Rust 写的，Android 上编译不了）⇒ fastapi 连带锁
# `<0.100.0`（见 android/app/build.gradle 的 pip 块）。而 delector 源码**桌面/Android
# 共用**、CI 只在 pydantic v2 + fastapi 0.141.1 下校验 —— 一旦有人用了 v2-only API，
# CI 全绿、APK 在 import 阶段直接崩，且没有任何门禁会拦（审计认定的最危险盲区）。
#
# 本守卫在普通套件内**静态**钉住"delector 不使用 pydantic v2-only API"。它是**近似**
# 而非等价：覆盖最常见的 API 形态回归，但不能替代真机覆盖安装点检（v1/v2 的校验/强转
# 等行为差异不在此覆盖范围）。

ANDROID_GRADLE = REPO_ROOT / "android" / "app" / "build.gradle"
DELECTOR_DIR = REPO_ROOT / "delector"

# pydantic v2 才有、v1 没有的名字：导入 / 装饰器 / 类属性 / 方法调用命中即 v1 下必炸。
_PYDANTIC_V2_ONLY = {
    # 导入名（from pydantic import X）
    "ConfigDict",
    "field_validator",
    "model_validator",
    "field_serializer",
    "model_serializer",
    "computed_field",
    "TypeAdapter",
    "RootModel",
    "AliasChoices",
    "AliasPath",
    # 仅 v2 才有的类属性 / 方法
    "model_config",
    "model_validate",
    "model_validate_json",
    "model_construct",
    "model_fields",
    "model_json_schema",
    "model_rebuild",
}
# v2 的 dump API（v1 对应 .dict()/.json()）：只能经 hasattr 兼容垫片使用
_PYDANTIC_V2_COMPAT_DUMPS = {"model_dump", "model_dump_json"}
# 仅 v2 支持的 Field 关键字（v1 用 regex= 而非 pattern= 等）
_PYDANTIC_V2_FIELD_KWARGS = {"pattern", "json_schema_extra", "union_mode"}


def _iter_delector_py() -> list[Path]:
    """delector/ 下全部 .py（含子包），供静态扫描。"""
    return sorted(DELECTOR_DIR.rglob("*.py"))


def test_android_pins_pydantic_v1_and_fastapi_pre_0100():
    """android/app/build.gradle 必须仍锁 pydantic<2 / fastapi<0.100（契约锚点）。

    这条不是"崇拜旧版本"，而是把 Android 的 Python 运行时契约钉成显式断言：一旦有人
    改了 Android 的 pin，本测试会红，逼他同步复核下一条守卫（delector 是否仍对
    pydantic v1 兼容），而不是让桌面/Android 两边悄悄漂移。
    """
    text = _read_guard_file(ANDROID_GRADLE)
    for needle, why in (
        ('install "pydantic<2.0.0"', "Android 面必须锁 pydantic v1（Chaquopy 装不了 Rust 扩展）"),
        ('install "fastapi<0.100.0"', "fastapi 需与 pydantic v1 配套，故锁在 0.100 之前"),
    ):
        assert needle in text, (
            f"{ANDROID_GRADLE} 缺少 {needle!r}（{why}）。\n"
            "若这是有意的升级，请同步复核 delector 是否仍对 pydantic v1 兼容，"
            "并更新本守卫与 build.gradle 里 pin 理由的注释。"
        )


def test_delector_avoids_pydantic_v2_only_api():
    """delector 源码不得使用 pydantic v2-only API（否则 CI 绿、Android APK 崩）。"""
    offenders = []
    for path in _iter_delector_py():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "pydantic":
                for alias in node.names:
                    if alias.name in _PYDANTIC_V2_ONLY:
                        offenders.append(f"{path}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.Attribute) and node.attr in _PYDANTIC_V2_ONLY:
                offenders.append(f"{path}:{node.lineno} .{node.attr}")
            elif isinstance(node, ast.Name) and node.id in _PYDANTIC_V2_ONLY:
                offenders.append(f"{path}:{node.lineno} {node.id}")
            elif isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg in _PYDANTIC_V2_FIELD_KWARGS:
                        offenders.append(f"{path}:{node.lineno} Field(..., {kw.arg}=...)")
    assert not offenders, (
        "delector 使用了 pydantic v2-only API —— Android 面是 pydantic v1，"
        "这些写法在 APK 里 import/调用即崩（而 CI 的 pydantic v2 不会报）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：改用 v1/v2 兼容写法；dump 类 API 走 hasattr 兼容垫片。"
    )


def test_pydantic_dump_api_guarded_by_hasattr_shim():
    """model_dump/model_dump_json 是 v2-only，必须经 hasattr 兼容垫片使用。"""
    offenders = []
    for path in _iter_delector_py():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(f".{attr}" in line for attr in _PYDANTIC_V2_COMPAT_DUMPS):
                if "hasattr(" not in line:
                    offenders.append(f"{path}:{i}: {line.strip()}")
    assert not offenders, (
        "model_dump/model_dump_json 是 pydantic v2 才有的方法，v1 下会 AttributeError；"
        '必须写成 `x.model_dump() if hasattr(x, "model_dump") else x.dict()` 的兼容垫片：\n  '
        + "\n  ".join(offenders)
    )


# ── 镜像构建上下文守卫（2026-10-03 审计 P0-2）──────────────────────────────────
# 背景：仓库根曾**不存在** .dockerignore，而 Dockerfile 第 14 行是 COPY . .。
# docker build 复制的是**工作树**而非 git tree ⇒ 开发者本地的 .env（内含
# DEEPSEEK_API_KEY 明文）与 *.db（用户真实数据）会被烤进镜像层。
# 关键点：这不只是「镜像里有冗余文件」——delector/server.py 的 load_env() 显式读
# os.getcwd()/.env，而 Dockerfile 的 WORKDIR 正是 /app ⇒ 容器**启动时真的会把
# 该 key 载入 os.environ**，并被 get_setting() 的 env 兜底实际使用。
#
# 本守卫双向钉死：
#   正向 —— 敏感/数据条目必须被排除（漏一条＝密钥或用户数据随镜像外流）；
#   反向 —— 不得用 * / ** 之类过宽模式把构建必需物（Dockerfile、delector/、
#          static/、requirements.txt）一并排掉，否则 build 会在 COPY 或 pip 阶段炸。

DOCKERIGNORE = REPO_ROOT / ".dockerignore"

# 必须出现在 .dockerignore 中的条目 → (为什么非排不可)
_DOCKERIGNORE_REQUIRED: dict[str, str] = {
    ".git": "版本库全量历史（对象、refs）不该进镜像：体积暴涨且泄露提交历史",
    ".env": ".env 是**明文密钥**（DEEPSEEK_API_KEY）；容器 WORKDIR=/app 恰好让 "
    "load_env() 在启动时把它载入 os.environ 并被实际使用",
    ".env.*": ".env.* 变体（.env.local / .env.production）同样是明文密钥",
    "*.db": "*.db 是**用户真实数据**（对话、账目）；进镜像层就是躺在镜像里的孤儿数据",
    "*.db-wal": "SQLite WAL 旁文件也是用户数据，且会与镜像内的旧 .db 错配",
    "*.db-shm": "SQLite 共享内存旁文件同样是用户数据",
    "*.apk": "*.apk 是构建产物（体积大、可被反编译），镜像用不到",
    "*.jks": "*.jks 是 Android 签名密钥：进镜像等于公开签名身份",
    "*.keystore": "*.keystore 同为签名密钥，必须与 *.jks 一起排除",
    "__pycache__": "__pycache__ 是宿主 Python 产出的 .pyc，与镜像内解释器版本可能不符",
    ".cache": ".cache 是工具链缓存目录，对运行时无价值",
    # Y6：.gitignore 已把下列本地明文敏感文件列为敏感，.dockerignore 漏排 ⇒
    # COPY . . 仍会把它们烤进镜像层（git tree 干净 ≠ 构建上下文干净）。
    "config.yaml": "config.yaml 在 .gitignore 的敏感清单内：本地 YAML 配置常夹明文口令/token",
    "config.yml": "config.yml 同为 .gitignore 敏感清单内的本地明文配置",
    "*.pem": "*.pem 是私钥/证书（PEM）：.gitignore 已列为敏感，进镜像等于公开私钥",
    "*.key": "*.key 同为私钥材料，.gitignore 已列为敏感",
    "*.local.json": "*.local.json 是本机私有 JSON 配置（可能夹 token），.gitignore 已列为敏感",
    "credentials.json": "credentials.json 字面即凭据文件，.gitignore 已列为敏感",
    "*.env": "*.env 覆盖任意 <name>.env 变体（Docker 的 * 可匹配空串，故连 .env 本身也命中）",
}

# 不得作为**整行**出现的过宽模式：会连构建必需物一起排掉
_DOCKERIGNORE_FORBIDDEN: dict[str, str] = {
    "*": "* 排掉一切：Dockerfile 的 COPY . . 会变成空目录，构建出的镜像无法启动",
    "**": "** 同样过宽，构建上下文会被清空",
    "/*": "/* 排掉仓库根下所有内容，等价于放弃构建",
    "delector": "排掉 delector 目录 = 排掉应用本体，uvicorn delector.server:app 直接 ModuleNotFoundError",
    "delector/": "排掉 delector 目录 = 排掉应用本体，uvicorn delector.server:app 直接 ModuleNotFoundError",
    "static/": "排掉 static 目录 = 前端静态资源丢失，页面 404",
    "Dockerfile": "排掉 Dockerfile 本身属于自相矛盾（它由 build context 读，"
    "一旦被排掉、后续有人改用 COPY 就会缺文件）",
    "requirements.txt": "排掉 requirements.txt：Dockerfile 第 10 行的 COPY requirements.txt . 会直接失败",
    "android": "排掉 android 目录：本仓库的 Android 打包面依赖它，不该由 Docker 镜像面单方面丢弃",
    "android/": "排掉 android 目录：本仓库的 Android 打包面依赖它，不该由 Docker 镜像面单方面丢弃",
}


def _dockerignore_lines() -> set[str]:
    """返回 .dockerignore 的有效行集合（去空白、去空行、去注释）。

    只做最小归一化，不解析 ! 取反/通配语义 —— 守卫要盯的是「条目在不在」，
    而不是替 Docker 重写一遍匹配器。
    """
    text = _read_guard_file(DOCKERIGNORE)
    return {s for line in text.splitlines() if (s := line.strip()) and not s.startswith("#")}


def test_dockerignore_excludes_secrets_and_databases() -> None:
    """.dockerignore 必须存在，并逐条排除密钥与用户数据条目。"""
    lines = _dockerignore_lines()

    # Y1：先钉"不得有取反行"，再钉条目齐全。
    # Docker 的 .dockerignore 语义是**后出现的行胜出**，`!` 前缀表示取反。
    # 因此在 `.env` 之后追加一行 `!.env` 会把 .env **重新纳入**构建上下文，
    # 而下面的"条目齐全"检查仍然绿（`.env` 那行还在文件里）——纯条目断言
    # 看不见这个旁路。守卫本身也必须零取反：排除表里出现 `!` 就没有别的
    # 可靠信号可判（我们不替 Docker 实现匹配器）。
    negated = sorted(s for s in lines if s.startswith("!"))
    assert not negated, (
        f"{DOCKERIGNORE} 出现取反条目 {negated}：取反行会让前面的排除失效——"
        "Docker 的 .dockerignore 是后出现的行胜出，在 `.env` 之后追加 `!.env` "
        "会把明文密钥**重新纳入**构建上下文，而条目齐全的检查仍会绿（假绿）。"
        "修法：删掉这些 `!` 开头的行；本守卫统一以「逐条排除」表达意图，"
        "不依赖取反语义。"
    )

    missing = [f"未排除 {needle!r}（{why}）" for needle, why in _DOCKERIGNORE_REQUIRED.items() if needle not in lines]
    assert not missing, (
        f"{DOCKERIGNORE} 缺少关键排除条目：\n"
        + "\n".join(missing)
        + "\n背景：Dockerfile 是 COPY . .，docker build 复制的是**工作树**而非 git tree，"
        "漏排的条目会随 docker build 进入镜像层；其中 .env 会被 /app 下的 load_env() "
        "在启动时真正载入 os.environ，*.db 则是用户真实数据。"
        "修法：在 .dockerignore 补上缺失条目，而不是删除或跳过本测试。"
    )


def test_dockerignore_does_not_exclude_build_inputs() -> None:
    """.dockerignore 不得用过宽模式把构建必需物排掉（否则 build 直接坏）。"""
    lines = _dockerignore_lines()

    offenders = [f"出现 {pattern!r}（{why}）" for pattern, why in _DOCKERIGNORE_FORBIDDEN.items() if pattern in lines]
    assert not offenders, (
        f"{DOCKERIGNORE} 出现了会破坏构建的过宽排除模式：\n"
        + "\n".join(offenders)
        + "\n.dockerignore 的职责是**逐条**排掉密钥/数据/产物，"
        "而不是整片排除 —— 请把 * 之类改成具体条目（.git / .env / *.db / __pycache__ …）。"
    )


# ── CI 作业超时护栏（2026-10-04 韧性审计 P1）──────────────────────────────────
# 背景：ci.yml 的 jobs.ci 没写 timeout-minutes，GitHub Actions 对 job 的默认上限是
# 360 分钟（6 小时）。一条卡死的测试（例如某个网络桩永不返回）会把 runner 烧满
# 六小时才红 —— 提交者早就改去下一件事了，"卡住的 PR 挡住 master"本身就是故障。
#
# 这里钉**上界**而不只是"有没有 timeout-minutes"：写成 `timeout-minutes: 3600`
# 的护栏形同虚设（比默认还宽），且从 YAML 上看不出意图。实测单次 CI 约 2.5–3.5min，
# 文件头注释自陈"PR 反馈预期 < 8min"，30 分钟已是 8–10 倍余量。

MAX_CI_JOB_TIMEOUT_MINUTES = 30


def _ci_job_block(job_name: str) -> str:
    """截出 ci.yml 里某个 job 的 YAML 块（按两空格缩进的同级键切分）。

    不引 pyyaml（它不在 requirements.txt，是 CI 内单独装的开发期工具）：
    这里只需要"这个 job 自己的字段"，按缩进层级切比全文搜索更严 ——
    别的 job 写了 timeout-minutes 不算数，得是 `ci` 这个 job 自己有。
    """
    return _job_block(CI_WORKFLOW, job_name)


def test_ci_job_has_bounded_timeout() -> None:
    """jobs.ci 必须有 timeout-minutes，且值 MUST ≤ 30（护栏必须有上界）。"""
    block = _ci_job_block("ci")

    match = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", block, re.MULTILINE)
    assert match, (
        f"{CI_WORKFLOW} 的 jobs.ci 没有 timeout-minutes：\n"
        "GitHub Actions 对单个 job 的默认上限是 360 分钟（6 小时），"
        "一条卡死的测试会把 runner 烧满六小时才红——提交者早改去下一件事了。"
        "\n修法：给 jobs.ci 加 `timeout-minutes: 15`（实测单次约 2.5–3.5min，"
        f"本守卫允许的上界是 {MAX_CI_JOB_TIMEOUT_MINUTES}）。"
    )

    minutes = int(match.group(1))
    assert 0 < minutes <= MAX_CI_JOB_TIMEOUT_MINUTES, (
        f"jobs.ci 的 timeout-minutes = {minutes}，超过上界 {MAX_CI_JOB_TIMEOUT_MINUTES}：\n"
        "写成 3600 之类的大值等于没设护栏（比 Actions 默认的 360 分钟还宽）。"
        "\n修法：改回 15；确需更长时先查清是哪一步变慢，而不是把闸门整体放开。"
    )


# ── Node 工具链显式化守卫（2026-10-05 清债轮 C 组）──────────────────────────────
# 背景：`tests/` 下有一批 wrapper 会 `node tools/*.mjs` 真跑 .mjs 行为探针（把前端真源码
# 切进 node:vm 沙箱执行）。但 ci.yml 此前**从不安装 node**，也没提过 setup-node ——
# wrapper 在 CI 上"恰好真跑"靠的是 `ubuntu-latest` runner 镜像**预装**的 Node 20.x。
#
# 这是**隐式依赖**，且失败模式极隐蔽：node 一旦不在 PATH，`shutil.which("node")` 守卫
# 走的是 `pytest.skip`（本地开发机没 node 不该红，是刻意设计）⇒ 在 CI 上会**静默跳过**
# 全部探针，测试全绿而探针根本没跑。绿灯掩盖了「回归守卫没执行」，比直接红更坏。
#
# 故 ci.yml 显式加一步 setup-node@v4 并固定 major '20'，本守卫钉住它：
#   1. 必须有 setup-node 步骤（防被删/被 revert 掉）；
#   2. node-version MUST 固定 major，MUST NOT 是 latest / lts / 20.x 之类浮动值
#      （浮动 ⇒ 不可复现构建）。
#
# 不引 pyyaml（沿用本文件既有的"按缩进层级切文本"手法，pyyaml 不在 requirements.txt，
# 是 CI 内单独装的开发期工具，守卫不该把它变成硬依赖）。

NODE_MAJOR = "20"


def _setup_node_with_block() -> str:
    """截出 ci.yml 里 setup-node 步骤的 `with:` 块（按缩进层级切文本）。

    只需要「这个步骤自己的 inputs」，按缩进切比全文搜索更严：
    别的步骤写了 `node-version` 不算数，得是 `actions/setup-node` 这步自己写。
    """
    text = _read_guard_file(CI_WORKFLOW)
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if "actions/setup-node@" in line)
    except StopIteration:
        pytest.fail(
            f"{CI_WORKFLOW} 找不到 actions/setup-node 步骤：\n"
            "tests/ 下的 .mjs 行为探针 wrapper 靠 `node tools/*.mjs` 真跑，此前靠 runner 镜像"
            "**预装**的 Node 20.x 侥幸运行（隐式依赖）。一旦镜像不再预装，node 不在 PATH → "
            "`shutil.which(\"node\")` 守卫 pytest.skip → 全部探针**静默跳过**、测试全绿，"
            "而回归守卫根本没执行。\n"
            "修法：在 jobs.ci 的 steps 里（setup-python 之后）加一步 actions/setup-node@v4 "
            f"并固定 node-version: \"{NODE_MAJOR}\"，而不是删掉本守卫。"
        )

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].strip() and not lines[i].startswith(" " * 8):
            end = i
            break
    return "\n".join(lines[start:end])


def test_ci_workflow_installs_node_explicitly() -> None:
    """ci.yml 必须显式安装 node —— 消除 wrapper 对 runner 预装的隐式依赖。

    与 `test_ci_job_has_bounded_timeout` 同族：守卫钉的是「fail 模式」。
    这里最隐蔽的失败模式不是红，是**绿**（探针被静默 skip），
    所以缺这一步 MUST 立刻红。
    """
    text = _read_guard_file(CI_WORKFLOW)
    assert "actions/setup-node@v" in text, (
        f"{CI_WORKFLOW} 没有 setup-node 步骤：.mjs 探针 wrapper 将退回依赖 runner 镜像预装的 "
        "Node —— node 缺失时它们会静默 skip（测试全绿而探针没跑）。"
    )

    block = _setup_node_with_block()
    match = re.search(r"""node-version:\s*['"]?([^'"\s]+)['"]?""", block)
    assert match, (
        f"setup-node 步骤没有声明 node-version（{block!r}）：\n"
        "不固定版本时 setup-node 会按 .nvmrc / runner 默认值解析，构建不可复现。"
    )

    version = match.group(1)
    assert version not in ("latest", "lts/*", "lts", "*"), (
        f"setup-node 的 node-version = {version!r}：\n"
        "latest/lts 是浮动值，构建不可复现（今天的绿灯明天可能红，且无法二分定位）。\n"
        f"修法：固定 major，例如 node-version: \"{NODE_MAJOR}\"。"
    )
    # 固定 major：纯数字或 v 前缀数字（'20' / 'v20'），拒绝 20.x / >=20 这类浮动写法
    assert re.fullmatch(r"v?\d+", version), (
        f"setup-node 的 node-version = {version!r}，不是固定的 major 版本：\n"
        f"MUST 写死 major（建议 \"{NODE_MAJOR}\"，与 runner 自带的 20.x 对齐），"
        "MUST NOT 写 20.x / >=20 / latest 之类会随时间漂移的值。"
    )
    assert version.lstrip("v") == NODE_MAJOR, (
        f"setup-node 的 node-version = {version!r}，与守卫钉定的 major {NODE_MAJOR!r} 不符：\n"
        "改 Node 大版本会让 .mjs 探针的真实执行结果变化（vm 沙箱行为与内置 API 都有差异），"
        "属需要显式复核的变更。确需升级请同步改本守卫的 NODE_MAJOR 并复核探针。"
    )


def test_ci_missing_node_fails_at_session_start() -> None:
    """根 conftest 必须让 CI 在 node 缺失时失败，而本地仍可由 wrapper skip。"""
    text = _read_guard_file(ROOT_CONFTEST)
    tree = ast.parse(text)
    hook = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "pytest_sessionstart"
        ),
        None,
    )
    assert hook is not None, "根 conftest.py 缺 pytest_sessionstart：CI 缺 node 时 29 处 wrapper 会静默 skip"

    block = ast.get_source_segment(text, hook)
    assert block is not None
    required_contract = [
        ('os.environ.get("CI")', "检查必须只在 CI 环境启用，本地缺 node 仍应 skip"),
        ('shutil.which("node")', "检查必须验证 node 是否真的在 PATH 上"),
        ("pytest.exit(", "CI 缺 node 时必须立即让 pytest 非零退出，不能继续到 wrapper skip"),
        ("returncode=1", "pytest 退出码必须明确为失败"),
    ]
    missing = [f"缺 {needle!r}（{why}）" for needle, why in required_contract if needle not in block]
    assert not missing, "pytest_sessionstart 没有钉住 CI 必需的 node 运行时：\n" + "\n".join(missing)


# ── CI 必需运行时清单守卫（2026-10 Fog 4）───────────────────────────────────────
# 上一轮（#106）把 node 从「静默 skip」升级为「CI 下必红」，消掉了 29 处
# `shutil.which("node")` 守卫的静默性。本节把「哪些二进制算 CI 必需」这条
# **判据本身**钉成清单，防止两种反向劣化：
#   1. 有人把**平台相关**的二进制（bash）也塞进 CI 必需 ⇒ 本地 Windows /
#      无 bash 环境被误伤成红（#106 明确不做「CI 零 skip」全局禁令）；
#   2. 有人把真正 CI 必需的项悄悄摘掉 ⇒ 又退回静默 skip。
#
# 判据（与 #106 一致）：**「CI 上缺了它 ⇒ 整批回归守卫静默失效」**。
# 满足此判据 ⇒ 进清单；只是「本机恰好没装 / 该平台本就没这命令」⇒ 不进。

# 判定为「CI 必需」的运行时：缺了它，CI 上大批回归守卫会静默 skip。
CI_REQUIRED_RUNTIMES: tuple[str, ...] = ("node",)

# 判定为「平台相关、非 CI 必需」的运行时：**刻意不进**清单，理由逐条钉住。
#   bash —— CI(ubuntu) 上必然存在（ubuntu-latest 镜像自带，且 GitHub Actions
#           的 run 步骤本身就以 bash 为默认 shell），缺失不现实；而它在
#           tests/test_server.py:2591 的用法是 `_find_bash()` 的**最后一招**
#           （前面还有 git-bash 路径探测 / `where bash` / PATH 扫描三套策略），
#           其 skip 语义是「本机找不到任何可用 bash」——这是**平台相关**的
#           合理 skip（Windows 无 Git-Bash/WSL 时就该跳），不是静默失效。
#           故 MUST NOT 升级为 fail。
PLATFORM_RELATED_RUNTIMES: tuple[str, ...] = ("bash",)


def _sessionstart_source() -> str:
    """取出根 conftest 里 pytest_sessionstart 的源码（缺失即 fail）。"""
    text = _read_guard_file(ROOT_CONFTEST)
    tree = ast.parse(text)
    hook = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "pytest_sessionstart"
        ),
        None,
    )
    assert hook is not None, (
        "根 conftest.py 缺 pytest_sessionstart：CI 缺 node 时 29 处 wrapper 会静默 skip，"
        "测试全绿而 .mjs 探针根本没跑。"
    )
    block = ast.get_source_segment(text, hook)
    assert block is not None
    return block


def _checked_runtimes_in_sessionstart() -> set[str]:
    """从 pytest_sessionstart 源码里抽出被 `shutil.which(...)` 检查的运行时名。

    只认**直接以字符串字面量传参**的调用（`shutil.which("node")`）。清单若被改成
    循环/变量间接传入，这里会抽不到 ⇒ 守卫失败，属刻意的「别玩花样」。
    """
    return set(re.findall(r"""shutil\.which\(\s*["']([^"']+)["']\s*\)""", _sessionstart_source()))


def test_ci_required_runtimes_manifest_matches_session_check() -> None:
    """「CI 必需运行时」清单 MUST 与 conftest 实际检查的集合逐字一致。

    双向钉：清单里有但没查（= 白写，守卫形同虚设）⇒ 红；
    查了但清单里没有（= 有人绕过清单偷偷加项）⇒ 红。
    """
    actual = _checked_runtimes_in_sessionstart()
    assert actual == set(CI_REQUIRED_RUNTIMES), (
        f"conftest 实际检查的运行时 = {sorted(actual)}，与清单 "
        f"{sorted(CI_REQUIRED_RUNTIMES)} 不一致。\n"
        "清单是判据的唯一落点：漏写 = 该项退回静默 skip；多写 = 绕过清单，"
        "下次没人知道它为什么被升级为 fail。\n"
        "修法：改 CI_REQUIRED_RUNTIMES，或改 conftest 使两者一致。"
    )


@pytest.mark.parametrize("runtime", CI_REQUIRED_RUNTIMES)
def test_ci_required_runtime_is_actually_checked(runtime: str) -> None:
    """清单里每一项 MUST 在 session 检查里被 shutil.which 真查（防清单空转）。"""
    assert runtime in _checked_runtimes_in_sessionstart(), (
        f"清单把 {runtime!r} 列为 CI 必需，但 conftest 的 session 检查里没有 "
        f"shutil.which({runtime!r})：清单与实现脱节，守卫形同虚设。"
    )


@pytest.mark.parametrize("runtime", PLATFORM_RELATED_RUNTIMES)
def test_platform_related_runtime_is_not_promoted_to_fail(runtime: str) -> None:
    """平台相关运行时 MUST NOT 被升级进「CI 必需」清单（防误伤本地 Windows）。

    这是本节最要紧的一条反向钉。把它升级为 fail 的诱惑是真实的——它同样
    长得像「CI 下缺了就静默 skip」——但判据不成立：

      * bash 在 CI(ubuntu) 上必然存在（镜像自带，且 Actions 的 run 步骤默认
        就是 bash），「CI 上缺 bash」不是现实场景；
      * tests/test_server.py 的用法是 `_find_bash()` 的**兜底分支**（前面还有
        三套探测策略），skip 语义是「本机找不到任何可用 bash」——Windows 上
        没装 Git-Bash/WSL 时跳过是**正确**行为，不是回归守卫静默失效。

    升级成 fail 的代价是实的：本地无 bash 的开发者会被红，且违背 #106 明确的
    「不做 CI 零 skip 全局禁令」（会误伤平台专用用例等合理 skip）。
    """
    assert runtime not in CI_REQUIRED_RUNTIMES, (
        f"{runtime!r} 被放进了 CI_REQUIRED_RUNTIMES：它是**平台相关**的合理 skip，"
        "不是 CI 必需运行时。\n"
        "升级为 fail 会让本地无 bash 的环境直接红，与 #106「只升级真正 CI 必需项、"
        "不做零 skip 全局禁令」相悖。\n"
        f"修法：从 CI_REQUIRED_RUNTIMES 移除 {runtime!r}。"
    )
    assert runtime not in _checked_runtimes_in_sessionstart(), (
        f"conftest 的 session 检查里出现 shutil.which({runtime!r})："
        f"{runtime!r} 是平台相关 skip，CI 下缺它 MUST NOT 让整个 session 失败。"
    )


def test_local_env_still_skips_instead_of_failing() -> None:
    """「CI 必需」判据 MUST 仍由 CI 环境变量把关——本地缺运行时只 skip 不红。

    这是 #106 的核心不变量：session 检查只在 CI 生效。判据一旦被改成恒真
    （例如误写成 `if True and not shutil.which(...)`），本地 Windows 开发机
    缺 node 就直接红；本测试用「判据表达式必须真的读 CI 环境变量」把它钉住。
    """
    block = _sessionstart_source()
    assert 'os.environ.get("CI")' in block, (
        "pytest_sessionstart 不再读 CI 环境变量：session 检查会在**本地**也生效，"
        "缺运行时的开发者直接被红（#106 明确：本地仍由各 wrapper 决定是否 skip）。\n"
        '修法：恢复 `if os.environ.get("CI") and ...` 的判据形态。'
    )
    # 恒真变异（`if True and ...`）会同时丢掉 CI 判据，上面一条即可杀死；
    # 这里再钉一条「判据不得被短路成与 CI 无关的常量」，双保险。
    assert not re.search(r"if\s+(True|1)\s*(and|:)", block), (
        "pytest_sessionstart 的判据被短路成恒真（`if True and ...`）："
        "session 检查会在本地也生效，与 #106 的「本地仍 skip」相悖。"
    )


def test_db_cleanup_needs_no_external_binary() -> None:
    """DB 清理 MUST NOT 依赖外部 `rm` 命令（它是纯跨平台 os.remove）。

    Fog 4 调研曾报「`delector/core/database.py` 约 :2086 的 test_cleanup 用
    `shutil.which("rm")` 做守卫，是第 8 处同类漏网」。**该前提经核实不成立**：
    全仓 `shutil.which("rm")` 命中 0 次，`def test_cleanup` 命中 0 次，
    `delector/core/database.py` 内 `shutil.which` 命中 0 次。真实的清理实现在
    `tests/db_cleanup.py::remove_db_files`，用的是 `os.remove`（跨平台，
    Windows 上同样可用，不经 shell、不需要 PATH 上有 rm）。

    本测试把「不依赖外部 rm」这条事实钉住：若将来有人图省事改成
    `subprocess(["rm", ...])`，或加一条 `shutil.which("rm")` 守卫，
    本测试立刻红——避免「Windows 上没有 rm ⇒ 静默 skip ⇒ 清理守卫失效」
    这类新 Fog。
    """
    helper = REPO_ROOT / "tests" / "db_cleanup.py"
    text = _read_guard_file(helper)
    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"""shutil\.which\(\s*["']rm["']\s*\)|subprocess""", line)
    ]
    assert not offenders, (
        f"tests/db_cleanup.py 出现了对外部命令的依赖：{offenders}\n"
        "清理逻辑 MUST 继续用 os.remove（跨平台、无需 PATH 上存在 rm）。\n"
        "改成 `subprocess(['rm', ...])` 或加 `shutil.which('rm')` 守卫会让 "
        "Windows 上没有 rm 的环境**静默 skip**清理守卫——正是 Fog 4 要消除的那类 Fog。"
    )
    # 反向确认：真的在用 os.remove（守卫不是空转）
    assert "os.remove(" in text, (
        "tests/db_cleanup.py 不再使用 os.remove：清理实现被改动过，"
        "请复核是否重新引入了对外部命令 / 平台专有 API 的依赖。"
    )


# ── Windows 产物验包闸的 CI 接线守卫（ADR-0021「替代投资#1」）────────────────────
# 背景：build-release.yml 此前对 Windows 产物**零验证**（pytest → 打包 → 压缩 → 上传，
# 从不真跑一次产物）。现在把 windows job 拆成「构建 / 验包 / 压缩」三步，验包用
# tools/verify_windows_portable.py 真启一次产物。本节把两件事钉死：
#   1. 验包步**存在**且**顺序早于**压缩与上传 —— 只断言"字符串在场"挡不住"挪到压缩之后"；
#   2. ci.yml 的 Windows 冒烟 job 存在，且其 paths 过滤清单逐项齐全（防"闸永不触发"）。

BUILD_RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-release.yml"
VERIFY_SCRIPT_NEEDLE = "tools/verify_windows_portable.py"

# 「打包面」路径清单：改任一文件都可能让 Windows 产物变坏 ⇒ 应点亮冒烟 job。
# 这是"闸的触发面"，与 ci.yml 内 dorny/paths-filter 的清单逐项同源。
PACKAGING_SURFACE_PATHS: tuple[str, ...] = (
    "package_windows.py",
    "desktop.py",
    "start.py",
    "requirements.txt",
    "requirements-desktop.txt",
    "tools/verify_windows_portable.py",
    ".github/workflows/build-release.yml",
)


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


def _packaging_filter_block() -> str:
    """截出 ci.yml 里 `filters: |` 起的路径清单块（按缩进切，只认该块自己的行）。"""
    text = _read_guard_file(CI_WORKFLOW)
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "filters: |")
    except StopIteration:
        pytest.fail(f"{CI_WORKFLOW} 找不到 `filters: |`（paths 过滤清单）：Windows 冒烟 job 的触发面丢失。")

    indent = len(lines[start]) - len(lines[start].lstrip())
    collected = []
    for line in lines[start + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        collected.append(line)
    return "\n".join(collected)


def test_build_release_verifies_before_compress_and_upload() -> None:
    """build-release.yml 的 windows job：验包步存在，且顺序早于压缩与上传。

    为什么不只断言"字符串在场"：把验包步整段挪到 Compress-Archive 之后，字符串依旧在场，
    而"坏产物已先进 zip/artifact"—— 闸形同虚设。故这里比**文本顺序**，钉死真实保证。
    """
    block = _job_block(BUILD_RELEASE_WORKFLOW, "build-windows")

    assert VERIFY_SCRIPT_NEEDLE in block, (
        f"{BUILD_RELEASE_WORKFLOW} 的 windows job 缺少验包步（未调用 {VERIFY_SCRIPT_NEEDLE}）：\n"
        "产物将不经真启验收就压缩上传（ADR-0021 替代投资#1 的核心闸被摘）。"
    )
    assert "Compress-Archive" in block, (
        f"{BUILD_RELEASE_WORKFLOW} 的 windows job 找不到 Compress-Archive：压缩步被改/被删？"
    )
    assert "actions/upload-artifact@" in block, (
        f"{BUILD_RELEASE_WORKFLOW} 的 windows job 找不到 upload-artifact 步。"
    )

    verify_at = block.index(VERIFY_SCRIPT_NEEDLE)
    compress_at = block.index("Compress-Archive")
    upload_at = block.index("actions/upload-artifact@")

    assert verify_at < compress_at, (
        f"{BUILD_RELEASE_WORKFLOW} 的验包步出现在压缩**之后**：坏产物已先进 zip。\n"
        "验包 MUST 早于压缩 —— 否则 zip 里装的就是那个没验过的包。"
    )
    assert verify_at < upload_at, (
        f"{BUILD_RELEASE_WORKFLOW} 的验包步出现在 upload-artifact **之后**：坏产物已被上传为 CI artifact。\n"
        "验包 MUST 早于上传。"
    )


def test_ci_has_windows_smoke_job_gated_on_packaging_paths() -> None:
    """ci.yml 必须有 Windows 冒烟 job，且其 paths 过滤清单逐项齐全（防"闸永不触发"）。"""
    text = _read_guard_file(CI_WORKFLOW)
    assert "windows-portable-smoke:" in text, (
        f"{CI_WORKFLOW} 缺 Windows 产物冒烟 job：打包面在合入 master 前坏了要等到发版日才炸。"
    )
    smoke = _job_block(CI_WORKFLOW, "windows-portable-smoke")
    assert "runs-on: windows-latest" in smoke, "冒烟 job 必须在 windows-latest 上跑（Linux 起不了 Windows exe）。"
    assert VERIFY_SCRIPT_NEEDLE in smoke, f"冒烟 job 必须真的调用验包脚本 {VERIFY_SCRIPT_NEEDLE}。"

    # 闸必须与 paths 过滤真正联动：与过滤脱钩则 job 恒不触发 = 闸形同虚设。
    assert "needs.windows-smoke-changes.outputs.packaging" in smoke, (
        "冒烟 job 没有引用 paths 过滤的输出（needs.windows-smoke-changes.outputs.packaging）："
        "job 会恒不触发 —— 这正是「闸永不触发」的失败形态。"
    )

    filter_block = _packaging_filter_block()
    missing = [p for p in PACKAGING_SURFACE_PATHS if f"'{p}'" not in filter_block]
    assert not missing, (
        f"{CI_WORKFLOW} 的 paths 过滤缺少打包面关键项：{missing}\n"
        "漏一项会让「只改该文件的 PR」不点亮冒烟 job —— 闸静默失效"
        "（本仓有过「正则永不命中」的教训）。"
    )


# ── 打包面检测步「失败不倒向红色」守卫（2026-10 master push 变红事故）──────────────
# 事故：windows-smoke-changes 的 dorny/paths-filter 在 **push** 事件下要以
# github.event.before 为基线做 git diff；checkout 浅克隆（fetch-depth: 1）时基线提交不在
# 本地对象库 ⇒ `git` 退出 128 ⇒ 检测步失败 ⇒ 整个 job 红 ⇒ master 变红
# （PR 走另一套基线机制，故同一 job 在 PR 上是绿的）。
#
# 两道互不替代的闸：
#   ① 修根因：检测步所在 job MUST 先 checkout **全历史**（fetch-depth: 0）；
#   ② fail-open：即便 ① 日后被删/回归，一个「只用来决定要不要跑」的检测步也 MUST NOT
#      有能力把 job（进而 master）弄红 —— 取不到干净结果时按「发生变更」处理，宁可多跑
#      一次闸，也不让过滤步成为红源。判据 MUST 依赖 steps.filter.outcome（continue-on-error
#      改写前的真实结果），而非 conclusion（它会被 continue-on-error 改写成 success）。


def _windows_smoke_changes_block() -> str:
    """截出 ci.yml 里 windows-smoke-changes job（检测步所在 job）的 YAML 块。"""
    return _job_block(CI_WORKFLOW, "windows-smoke-changes")


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


def test_packaging_detect_checkout_fetches_full_history() -> None:
    """检测步所在 job 的 checkout MUST 带 fetch-depth: 0（防日后被删 ⇒ 重现 master 红）。

    为什么这条在「失败不倒向」之外必须独立存在：fetch-depth: 0 修的是**根因**
    （push 下 paths-filter 拿不到 github.event.before 基线 ⇒ git exit 128）；fail-open
    只是**兜底**。只留 fail-open，会让每次因基线缺失而全量点亮 windows runner（昂贵且
    掩盖真问题）；只留 fetch-depth，一旦有人顺手删掉就再次红。两者缺一不可。
    """
    detect = _windows_smoke_changes_block()

    checkout = _step_using(detect, "actions/checkout@")
    assert re.search(r"fetch-depth:\s*0\b", checkout), (
        f"{CI_WORKFLOW} 的 windows-smoke-changes checkout 缺 `fetch-depth: 0`：\n{checkout}\n"
        "dorny/paths-filter 在 push 事件下以 github.event.before 为基线做 git diff，浅克隆"
        "（默认 fetch-depth: 1）时基线提交不在本地对象库 ⇒ git exit 128 ⇒ 检测步把 master"
        "弄红（PR 走另一套基线机制故绿）。修法：给该 checkout 的 with: 加 fetch-depth: 0。"
    )

    # 顺序：checkout MUST 早于 paths-filter，否则 paths-filter 仍在没有 .git 的目录里跑。
    steps = _steps_of(detect)
    checkout_idx = next(i for i, s in enumerate(steps) if "actions/checkout@" in s)
    filter_idx = next(i for i, s in enumerate(steps) if "dorny/paths-filter@" in s)
    assert checkout_idx < filter_idx, (
        f"{CI_WORKFLOW} 的 checkout 出现在 dorny/paths-filter **之后**：\n"
        "paths-filter 需要在已检出的仓库里跑 git diff，checkout MUST 早于它。"
    )


def test_packaging_filter_step_is_fail_open() -> None:
    """「检测变更」步 MUST NOT 有能力把 job（进而 master）弄红：失败 ⇒ 视为发生变更。

    失败形态：检测步只决定「要不要跑闸」，它红 ⇒ 整个 job 红 ⇒ master push 变红，而 CI
    的本意是「宁可多跑一次闸」也不能让过滤步成为红源。故：
      1. 检测步 MUST 带 continue-on-error: true（失败不把 job 弄红）；
      2. 判定 MUST 以 steps.filter.outcome 兜底 —— 取不到干净 success 结果时缺省为
         「发生变更」（fail-open 到跑闸）。MUST 用 outcome 而非 conclusion：continue-on-error
         会把失败的 conclusion 改写成 success，只有 outcome 保留真实失败，据此才能判
         「取不到结果」。
    """
    detect = _windows_smoke_changes_block()

    assert "continue-on-error: true" in detect, (
        f"{CI_WORKFLOW} 的打包面检测步缺 `continue-on-error: true`：\n"
        "该步只用来决定「要不要跑闸」，一旦失败就红 ⇒ 有能力把 master push 弄红。\n"
        "修法：给该步加 continue-on-error: true，并把判定改为 fail-open。"
    )

    assert re.search(r"steps\.filter\.outcome\s*==\s*'success'", detect), (
        f"{CI_WORKFLOW} 的打包面判定未以 steps.filter.outcome 兜底：\n"
        "检测步失败/被跳过时会取不到 outputs，若判定直接依赖 outputs，缺省即「无变更」"
        "= fail-closed，闸静默失效（而「过滤步红 ⇒ master 红」正是要消除的失败形态）。"
    )
    assert re.search(r"\|\|\s*'true'", detect), (
        f"{CI_WORKFLOW} 的打包面判定缺 'true' 缺省值：\n"
        "检测步「取不到结果」时 MUST 缺省为「发生变更」（fail-open 到跑闸），"
        "而非缺省为「无变更」。"
    )


def test_packaging_surface_manifest_stays_readable_in_workflow() -> None:
    """「打包面」清单 MUST 仍留在 workflow 里逐项可读（不藏进 action 的隐式行为）。

    与 `test_ci_has_windows_smoke_job_gated_on_packaging_paths` 互补：那条钉「清单在闸的
    触发面（filters）里齐全」，这条钉「清单本身仍在 workflow 文本内、可读、可复跑验证」，
    防止有人把触发面改写成 action 的隐式默认路径（那份清单将无法被本守卫逐项核对）。
    """
    filter_block = _packaging_filter_block()
    missing = [p for p in PACKAGING_SURFACE_PATHS if p not in filter_block]
    assert not missing, (
        f"{CI_WORKFLOW} 的 paths 过滤缺打包面关键项：{missing}\n"
        "「哪些文件算打包面」这份清单 MUST 留在 workflow 里（可读、可复跑验证），"
        "且逐项齐全 —— 漏项会让「只改该文件的 PR」不点亮冒烟 job（闸静默失效）。"
    )
