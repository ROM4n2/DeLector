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
