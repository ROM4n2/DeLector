# -*- coding: utf-8 -*-
"""``tools/check_silent_degradation.py`` 的单元测试（Task 8：无静默降级机械闸）。

覆盖任务书 Step 4 逐字要求的三件：
1. 三条判据各有**阳性 + 阴性**样本 —— 阴性样本 MUST 让判据对「有痕迹的处理」保持沉默
   （否则闸会逼着人把日志删掉，比不修更坏）；
2. 空理由抑制 = 违规（``silent-ok:`` 后不写 REASON 不算豁免）；
3. 退出码语义：0=通过 / 1=有未豁免站点 / 2=环境不可用。

纪律：全部用 ``tmp_path`` 造合成树，**绝不**让被测模块扫描真仓库
（本文件除 CI 接线守卫会读 ``.github/workflows/ci.yml`` 外，不读任何 delector/ 与 tools/
的源码内容；判定器本身经 importlib 按路径加载，零 import 期副作用）。
"""

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "tools" / "check_silent_degradation.py"


def _load_module() -> Any:
    """按文件路径加载判定器模块（用真对象，避免 import 期污染 sys.modules）。"""
    if not _SCRIPT.exists():
        pytest.fail(f"判定器脚本不存在：{_SCRIPT}（无静默降级机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_silent_degradation", _SCRIPT)
    assert spec is not None and spec.loader is not None, f"无法加载判定器脚本：{_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_tree(
    tmp_path: Path,
    files: dict[str, str],
    *,
    dirs: tuple[str, ...] = ("delector", "tools"),
) -> Path:
    """造一个最小扫描树：``root/<dirs…>`` + 指定相对路径的文件。"""
    root = tmp_path / "repo"
    for sub in dirs:
        (root / sub).mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    return root


_CLEAN_FILE = "def ok() -> int:\n    return 1\n"


# ── C1：静默吞错（except 体只有 pass；Task 8b 收窄：continue 不再命中）────────────────────────────────


_C1_PASS_SAMPLE = (
    "def cleanup() -> None:\n"  # 1
    "    try:\n"  # 2
    "        risky()\n"  # 3
    "    except Exception:\n"  # 4  ← 命中行
    "        pass\n"  # 5
)

_C1_CONTINUE_SAMPLE = (
    "def pick(candidates) -> None:\n"  # 1
    "    for item in candidates:\n"  # 2
    "        try:\n"  # 3
    "            use(item)\n"  # 4
    "        except ValueError:\n"  # 5  ← 旧判据的命中行；Task 8b 收窄后不再命中（负样本）
    "            continue\n"  # 6
)


def _c1_source_with_body(*body_lines: str) -> str:
    """构造 ``except Exception as exc:`` + 指定体的样本（体缩进 8 格）。"""
    body = "".join(f"        {line}\n" for line in body_lines)
    return "def f() -> None:\n" "    try:\n" "        risky()\n" "    except Exception as exc:\n" + body


def test_c1_flags_pass_only_handler() -> None:
    """阳性：体只有 pass ⇒ C1 命中，行号=except 行，片段为折叠后的源码。"""
    module = _load_module()
    hits = module.scan_source(_C1_PASS_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C1", 4)]
    assert hits[0].snippet == "except Exception: pass"


def test_c1_ignores_continue_only_handler_after_narrowing() -> None:
    """阴性（Task 8b 收窄）：体只有 continue（循环内逐项跳过）⇒ C1 **不再**命中。

    机制：``pass`` 掐灭一条错误路径；``continue`` 是循环内逐项策略，其余迭代照常执行，
    与「有意的逐项过滤」形态不可区分。该收窄会漏掉的缺陷类（逐项跳过掩盖系统性失败）
    已在闸的模块头显式登记 —— 本用例与那条登记互为锁：谁想重新放宽 C1，先过这里。
    """
    module = _load_module()
    hits = module.scan_source(_C1_CONTINUE_SAMPLE)
    assert [hit for hit in hits if hit.criterion == "C1"] == []


@pytest.mark.parametrize(
    "statement",
    [
        'logging.warning("risky failed: %s", exc)',
        'logger.warning("risky failed")',
        '_logger.error("risky failed", exc_info=True)',
        'warnings.warn("risky failed")',
    ],
)
def test_c1_ignores_handler_body_that_logs(statement: str) -> None:
    """阴性：体内有 logging / warnings 调用 ⇒ 不算静默（闸 MUST NOT 逼人删日志）。"""
    module = _load_module()
    hits = module.scan_source(_c1_source_with_body(statement))
    assert [hit for hit in hits if hit.criterion == "C1"] == []


@pytest.mark.parametrize("body_lines", [["raise"], ["return"], ["return None"], ["pass", "logging.warning(\"x\")"]])
def test_c1_ignores_handler_body_with_raise_or_return_value(body_lines: list[str]) -> None:
    """阴性：raise / 带值 return（以及「pass + 日志」混合体）都不是静默吞错。"""
    module = _load_module()
    hits = module.scan_source(_c1_source_with_body(*body_lines))
    assert [hit for hit in hits if hit.criterion == "C1"] == []


# ── C2：裸 except ───────────────────────────────────────────────────────────────


_C2_SAMPLE = (
    "def f() -> None:\n"  # 1
    "    try:\n"  # 2
    "        risky()\n"  # 3
    "    except:\n"  # 4  ← 命中行
    "        cleanup()\n"  # 5
)

_C2_TYPED_SAMPLE = (
    "def f() -> None:\n"
    "    try:\n"
    "        risky()\n"
    "    except ValueError:\n"
    "        cleanup()\n"
)

_BARE_PASS_SAMPLE = (
    "try:\n"  # 1
    "    risky()\n"  # 2
    "except:\n"  # 3  ← C1 与 C2 在同一行双双命中
    "    pass\n"  # 4
)


def test_c2_flags_bare_except() -> None:
    """阳性：裸 except（无类型）⇒ C2 命中，片段为 except 头。"""
    module = _load_module()
    hits = module.scan_source(_C2_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C2", 4)]
    assert hits[0].snippet == "except:"


def test_c2_ignores_typed_except() -> None:
    """阴性：带类型且体非 pass/continue ⇒ 无任何命中。"""
    module = _load_module()
    assert module.scan_source(_C2_TYPED_SAMPLE) == []


def test_bare_except_with_pass_matches_both_criteria() -> None:
    """语义：``except: pass`` 同时命中 C1 与 C2（两行输出指向同一行，互不吞并）。"""
    module = _load_module()
    hits = module.scan_source(_BARE_PASS_SAMPLE)
    assert sorted((hit.criterion, hit.line) for hit in hits) == [("C1", 3), ("C2", 3)]


# ── C3：证书校验静默关闭（封闭函数内无 logging / warnings 调用）─────────────────


_C3_UNVERIFIED_SAMPLE = (
    "import ssl\n"  # 1
    "\n"  # 2
    "def connect(host) -> object:\n"  # 3
    "    ctx = ssl._create_unverified_context()\n"  # 4  ← 命中行
    "    return ctx\n"  # 5
)

_C3_CERT_NONE_SAMPLE = (
    "import ssl\n"  # 1
    "\n"  # 2
    "def client() -> object:\n"  # 3
    "    ctx = ssl.create_default_context()\n"  # 4
    "    ctx.check_hostname = False\n"  # 5
    "    ctx.verify_mode = ssl.CERT_NONE\n"  # 6  ← 命中行
    "    return ctx\n"  # 7
)

_C3_VERIFY_FALSE_SAMPLE = (
    "import httpx\n"  # 1
    "\n"  # 2
    "def probe(url) -> object:\n"  # 3
    "    return httpx.get(url, verify=False)\n"  # 4  ← 命中行
)

_C3_VERIFY_TRUE_SAMPLE = (
    "import httpx\n"
    "\n"
    "def probe(url) -> object:\n"
    "    return httpx.get(url, verify=True)\n"
)

_C3_OTHER_FUNCTION_LOGS_SAMPLE = (
    "import ssl\n"  # 1
    "import logging\n"  # 2
    "\n"  # 3
    "def unrelated() -> None:\n"  # 4
    '    logging.warning("无关日志")\n'  # 5
    "\n"  # 6
    "def connect() -> object:\n"  # 7
    "    return ssl._create_unverified_context()\n"  # 8  ← 命中行（另一函数的日志不清洗本函数）
)


def _c3_source_with_logging(statement: str) -> str:
    """构造「封闭函数内有观测」的样本（日志语句在 ssl 站点之前）。"""
    return (
        "import ssl\n"
        "\n"
        "def connect(host) -> object:\n"
        f"    {statement}\n"
        "    return ssl._create_unverified_context()\n"
    )


def test_c3_flags_unverified_context_without_logging() -> None:
    """阳性：函数里关了证书校验且零日志 ⇒ C3 命中。"""
    module = _load_module()
    hits = module.scan_source(_C3_UNVERIFIED_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C3", 4)]
    assert "_create_unverified_context" in hits[0].snippet


def test_c3_flags_cert_none() -> None:
    """阳性：``ssl.CERT_NONE`` 且零日志 ⇒ C3 命中。"""
    module = _load_module()
    hits = module.scan_source(_C3_CERT_NONE_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C3", 6)]
    assert "CERT_NONE" in hits[0].snippet


def test_c3_flags_verify_false() -> None:
    """阳性：``verify=False`` 且零日志 ⇒ C3 命中（行号=该关键字的行）。"""
    module = _load_module()
    hits = module.scan_source(_C3_VERIFY_FALSE_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C3", 4)]
    assert "verify=False" in hits[0].snippet


def test_c3_ignores_verify_true() -> None:
    """阴性：``verify=True`` 不是降级 ⇒ 无命中。"""
    module = _load_module()
    assert module.scan_source(_C3_VERIFY_TRUE_SAMPLE) == []


@pytest.mark.parametrize(
    "statement",
    [
        'logging.warning("证书校验被关闭：%s", "probe")',
        'logger.warning("证书校验被关闭")',
        '_logger.error("证书校验被关闭", exc_info=True)',
        'warnings.warn("证书校验被关闭")',
    ],
)
def test_c3_ignores_site_when_enclosing_function_logs(statement: str) -> None:
    """阴性：封闭函数里有 logging / warnings 调用 ⇒ 有观测，不命中。"""
    module = _load_module()
    assert module.scan_source(_c3_source_with_logging(statement)) == []


def test_c3_scope_is_per_function_not_per_file() -> None:
    """阴性对照：日志在**别的**函数里 ⇒ 不清洗本函数的站点（作用域各自独立）。"""
    module = _load_module()
    hits = module.scan_source(_C3_OTHER_FUNCTION_LOGS_SAMPLE)
    assert [(hit.criterion, hit.line) for hit in hits] == [("C3", 8)]


# ── 豁免层：silent-ok 只在注释里生效；空理由 = 违规 ─────────────────────────────


_SUPPRESS_SAME_LINE_SAMPLE = (
    "def f() -> None:\n"  # 1
    "    try:\n"  # 2
    "        risky()\n"  # 3
    "    except Exception:  # silent-ok: 候选失败即跳过，上层有汇总日志\n"  # 4  ← 命中行（同行注释豁免）
    "        pass\n"  # 5
)

_SUPPRESS_LINE_ABOVE_SAMPLE = (
    "def f() -> None:\n"  # 1
    "    try:\n"  # 2
    "        risky()\n"  # 3
    "    # silent-ok: 注释在命中行的上一行\n"  # 4
    "    except Exception:\n"  # 5  ← 命中行
    "        pass\n"  # 6
)

_SUPPRESS_EMPTY_REASON_SAMPLE = (
    "def f() -> None:\n"  # 1
    "    try:\n"  # 2
    "        risky()\n"  # 3
    "    except Exception:  # silent-ok:\n"  # 4  ← 命中行（空 REASON = 抑制无效）
    "        pass\n"  # 5
)

_STRING_LOOKALIKE_SUPPRESSION_SAMPLE = (
    "def f() -> None:\n"  # 1
    "    try:\n"  # 2
    '        risky(why="silent-ok: 假豁免")\n'  # 3  ← 字符串字面量（不是注释）；命中行的上一行
    "    except Exception:\n"  # 4  ← 命中行
    "        pass\n"  # 5
)


def test_suppression_same_line_exempts_and_records_reason() -> None:
    """同行注释 ``silent-ok: REASON`` ⇒ 豁免，理由被完整记录。"""
    module = _load_module()
    comments = module.comments_by_line(_SUPPRESS_SAME_LINE_SAMPLE)
    exempt, reason, empty_reason = module.suppression_state(comments, 4)
    assert exempt is True
    assert "候选失败即跳过" in reason
    assert empty_reason is False


def test_suppression_line_above_exempts() -> None:
    """上一行注释 ``silent-ok: REASON`` ⇒ 豁免。"""
    module = _load_module()
    comments = module.comments_by_line(_SUPPRESS_LINE_ABOVE_SAMPLE)
    exempt, reason, empty_reason = module.suppression_state(comments, 5)
    assert exempt is True
    assert "上一行" in reason
    assert empty_reason is False


def test_suppression_empty_reason_is_rejected() -> None:
    """空理由（``silent-ok:`` 后什么都不写）⇒ 不豁免，且被标记为空理由抑制。"""
    module = _load_module()
    comments = module.comments_by_line(_SUPPRESS_EMPTY_REASON_SAMPLE)
    exempt, reason, empty_reason = module.suppression_state(comments, 4)
    assert exempt is False
    assert reason == ""
    assert empty_reason is True


def test_suppression_marker_in_string_literal_is_not_a_comment() -> None:
    """标记出现在字符串字面量里 ⇒ 不算豁免（豁免只认注释，tokenize 口径）。"""
    module = _load_module()
    comments = module.comments_by_line(_STRING_LOOKALIKE_SUPPRESSION_SAMPLE)
    exempt, _reason, empty_reason = module.suppression_state(comments, 4)
    assert exempt is False
    assert empty_reason is False


# ── 退出码语义：0 / 1 / 2（run_scan 与 CLI main 两层）────────────────────────────


def test_run_scan_returns_zero_on_clean_tree(tmp_path: Path) -> None:
    """0 = 通过：无任何命中。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _CLEAN_FILE, "tools/clean.py": _CLEAN_FILE})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "通过" in out.getvalue()


def test_run_scan_returns_one_on_violation_and_prints_hit_line(tmp_path: Path) -> None:
    """1 = 违规：输出 MUST 含 ``file:line | criterion | 'snippet'`` 逐行清单。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _C1_PASS_SAMPLE})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 1
    assert "delector/mod.py:4 | C1 | 'except Exception: pass'" in out.getvalue()
    assert "违规" in err.getvalue()


def test_run_scan_report_only_still_returns_zero(tmp_path: Path) -> None:
    """--report-only：命中照打，但退出码恒 0（只报告不判红）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _C1_PASS_SAMPLE})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, report_only=True, out=out, err=err) == 0
    assert "delector/mod.py:4 | C1 |" in out.getvalue()
    assert "report-only" in out.getvalue()


def test_run_scan_exempt_site_exits_zero_and_prints_reason(tmp_path: Path) -> None:
    """被豁免的站点不判红，但 MUST 逐行打印（绝不静默豁免）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _SUPPRESS_SAME_LINE_SAMPLE})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 0
    assert "[exempt] silent-ok: 候选失败即跳过" in out.getvalue()


def test_run_scan_empty_reason_site_still_violation(tmp_path: Path) -> None:
    """空理由抑制 ⇒ 仍判 1，且输出标注「REASON 为空：抑制无效」。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _SUPPRESS_EMPTY_REASON_SAMPLE})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 1
    assert "REASON 为空" in out.getvalue()


def test_run_scan_returns_two_on_missing_root(tmp_path: Path) -> None:
    """2 = 环境不可用：扫描根不存在。"""
    module = _load_module()
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(tmp_path / "absent", out=out, err=err) == 2
    assert "环境不可用" in err.getvalue()


def test_run_scan_returns_two_on_missing_scan_dir(tmp_path: Path) -> None:
    """2 = 环境不可用：缺 tools/ 扫描面（闸空转 MUST NOT 静默放行）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _CLEAN_FILE}, dirs=("delector",))
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "扫描面缺失" in err.getvalue()


def test_run_scan_returns_two_on_empty_scan_surface(tmp_path: Path) -> None:
    """2 = 环境不可用：两个扫描面都存在但一个 .py 都没有（空转）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "扫描面为空" in err.getvalue()


def test_run_scan_returns_two_on_unparseable_file(tmp_path: Path) -> None:
    """2 = 环境不可用：文件无法解析 ⇒ 无法判定 ⇒ 拒绝放行（不是判 0）。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/broken.py": "def broken(:\n"})
    out, err = io.StringIO(), io.StringIO()
    assert module.run_scan(root, out=out, err=err) == 2
    assert "无法解析" in err.getvalue()


def test_main_cli_violation_returns_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：不带 --report-only 时违规 ⇒ 退出码 1。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _C1_PASS_SAMPLE})
    assert module.main(["--root", str(root)]) == 1
    assert "delector/mod.py:4 | C1 |" in capsys.readouterr().out


def test_main_cli_report_only_returns_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：--report-only ⇒ 退出码 0。"""
    module = _load_module()
    root = _make_tree(tmp_path, {"delector/mod.py": _C1_PASS_SAMPLE})
    assert module.main(["--root", str(root), "--report-only"]) == 0
    assert "delector/mod.py:4 | C1 |" in capsys.readouterr().out


def test_main_cli_missing_root_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 接线：环境不可用 ⇒ 退出码 2。"""
    module = _load_module()
    assert module.main(["--root", str(tmp_path / "absent")]) == 2
    assert "环境不可用" in capsys.readouterr().err


# ── CI 接线守卫（这份闸的 fail-loud 接线本身就是契约）──────────────────────────


def test_ci_workflow_wires_the_gate_fail_loud() -> None:
    """ci.yml 必须有 `silent-degradation` job 真跑判定器，且 job / 步骤均无容错键。"""
    yaml_module = pytest.importorskip("yaml")
    workflow_path = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    doc = yaml_module.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert "silent-degradation" in jobs, "ci.yml 缺少 silent-degradation job（闸没接线）"
    job = jobs["silent-degradation"]
    assert "continue-on-error" not in job, "job 级容错键会让闸变摆设（fail-loud 违约）"
    runs = [str(step.get("run", "")) for step in job["steps"]]
    assert any("tools/check_silent_degradation.py" in run for run in runs), "job 未接线判定器脚本"
    assert all("continue-on-error" not in step for step in job["steps"]), "步骤级容错键会让闸变摆设"