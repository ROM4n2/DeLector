# -*- coding: utf-8 -*-
"""仓库治理守卫：master 直推范围、pytest 分片完整性与 Android 本机配置隔离。"""

import importlib.util
import json
import re
import subprocess
from collections import Counter
from typing import Any, NamedTuple, Sequence

import pytest
from _ci_hardening_support import (
    ANDROID_APP_BUILD_GRADLE,
    CI_WORKFLOW,
    COST_GUARD_SHARDS,
    REPO_ROOT,
    _ci_job_block,
    _job_block,
    _read_guard_file,
)

# ── master 直推范围机械闸（P1-1：分支纪律此前没有机械闸）─────────────────────────
# 背景：docs/reviews/2026-10-16-commit-rhythm-and-git-management-audit.md P1-1 ——
# 2026-10-09~14 有 25 个 feat/fix/ci/test/perf 提交直推 master（含生产代码与 CI 定义），
# 且已实发 f49d359 推红事故。修法 = 一条廉价机械闸：master 上**非 merge** 提交的改动面
# MUST ⊆ 白名单。本闸三件：① 可测判定器 tools/check_master_commit_scope.py（纯函数 +
# CLI 退出码 0/1/2）；② .githooks/pre-push 接线；③ 一份 workflow 新增 job（仅 push→master）。
#
# 断言纪律：判定器用**真调用**（非字符串在场）；CLI 退出码用注入式 git stub（零子进程 ——
# 遵守计划「新增测试 MUST NOT 起无界子进程链」）。两条豁免 MUST 各有独立用例，且用例对
# 豁免是**敏感**的（删豁免 ⇒ 用例红，见计划 Step 4 变异自证）。

MASTER_SCOPE_SCRIPT = REPO_ROOT / "tools" / "check_master_commit_scope.py"
PRE_PUSH_HOOK = REPO_ROOT / ".githooks" / "pre-push"

#: 白名单内样本（逐条命中一条规则：目录前缀 / 精确名）。
_ALLOWLIST_ALLOWED: tuple[str, ...] = (
    "WORKMEMORY/work.log",
    "docs/reviews/x.md",
    "README.md",
    "CHANGELOG.md",
    "static/index.html",
    "static/sw.js",
    "android/app/build.gradle",
    "delector/core/version.py",
)
#: 出界样本：生产代码（P1-1 里 25 个直推提交最典型的越界面）。
_ALLOWLIST_OFFENDER = "delector/services/llm_client.py"
#: git 默认合并提交 subject 形态（审计实测：全部为 "Merge pull request #N from …"）。
_MERGE_SUBJECT = "Merge pull request #143 from dev/feat-x"
_ZERO_SHA = "0" * 40


class _FakeCommit(NamedTuple):
    """stub 用的一条提交记录（subject + 改动面 + 是否 root / committer / parents）。"""

    subject: str
    files: tuple[str, ...]
    is_root: bool = False
    committer_name: str = "Developer"
    committer_email: str = "dev@example.com"
    parents: tuple[str, ...] = ("deadbeef",)


class _FakeGit:
    """注入式 git stub：零子进程，覆盖判定器用到的只读命令（rev-list / log / diff-tree）。"""

    def __init__(self, commits: dict[str, _FakeCommit]) -> None:
        self.commits = commits
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        self.calls.append(list(args))
        if args[0] == "rev-list" and "--no-merges" in args:
            return "".join(f"{sha}\n" for sha in self.commits)
        if args[0] == "rev-list" and "--parents" in args:
            sha = args[-1]
            c = self.commits[sha]
            parents = () if c.is_root else c.parents
            return " ".join((sha, *parents)) + "\n"
        if args[0] == "log":
            sha = args[-1]
            c = self.commits[sha]
            fmt = next((a for a in args if a.startswith("--format=")), "")
            if "%x00" in fmt:
                parents = () if c.is_root else c.parents
                parents_str = " ".join(parents)
                return f"{c.subject}\x00{c.committer_name}\x00{c.committer_email}\x00{parents_str}\n"
            return c.subject + "\n"
        if args[0] == "diff-tree":
            return "".join(f"{name}\n" for name in self.commits[args[-1]].files)
        raise AssertionError(f"未预期的 git 调用：{args}")


def _load_master_scope_module() -> Any:
    """按文件路径加载判定器模块（用真对象，避免 import 期污染 sys.modules）。"""
    if not MASTER_SCOPE_SCRIPT.exists():
        pytest.fail(f"判定器脚本不存在：{MASTER_SCOPE_SCRIPT}（master 直推机械闸缺失）")
    spec = importlib.util.spec_from_file_location("check_master_commit_scope", MASTER_SCOPE_SCRIPT)
    assert spec is not None and spec.loader is not None, f"无法加载判定器脚本：{MASTER_SCOPE_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_scope_allows_whitelisted_files() -> None:
    """白名单内（簿记 / 文档 / 版本面）⇒ 无违规理由。"""
    module = _load_master_scope_module()
    assert module.check_scope(_ALLOWLIST_ALLOWED, subject="docs: 更新簿记") == []


def test_check_scope_flags_out_of_allowlist_file() -> None:
    """出界文件 ⇒ 判红；白名单被放宽（如改成 **）时本用例 MUST 红。"""
    module = _load_master_scope_module()
    reasons = module.check_scope([*_ALLOWLIST_ALLOWED, _ALLOWLIST_OFFENDER], subject="feat: 越界")
    assert reasons, "出界文件未被判红：白名单被放宽（如改成 **）时本用例 MUST 红"
    assert any(_ALLOWLIST_OFFENDER in reason for reason in reasons), reasons


def test_check_scope_exempts_merge_commit() -> None:
    """真实合并提交豁免（is_merge_commit=True）：删掉 merge 豁免时本用例 MUST 红。"""
    module = _load_master_scope_module()
    assert (
        module.check_scope(
            [_ALLOWLIST_OFFENDER],
            subject=_MERGE_SUBJECT,
            is_merge_commit=True,
        )
        == []
    ), "合并提交未被豁免：删掉 merge 豁免时本用例 MUST 红"


def test_check_scope_rejects_merge_subject_spoof_on_single_parent() -> None:
    """合并形标题 + 单父（is_merge_commit=False）+ 出界文件 ⇒ 必须被判红。

    为什么严格更安全：防止直推生产代码时通过在 commit 标题写 'Merge pull request #...'
    绕过 master 直推白名单检查（关闭既有伪造路径）。
    """
    module = _load_master_scope_module()
    reasons = module.check_scope(
        [_ALLOWLIST_OFFENDER],
        subject=_MERGE_SUBJECT,
        is_merge_commit=False,
    )
    assert reasons, "伪造合并标题在单父提交上必须被判红"


def test_check_scope_exempts_github_integrated() -> None:
    """E 纯函数：github_integrated=True 时无论改动面是什么均豁免。"""
    module = _load_master_scope_module()
    assert (
        module.check_scope(
            [_ALLOWLIST_OFFENDER],
            subject="fix(x): something",
            github_integrated=True,
        )
        == []
    )
    assert module.check_scope(
        [_ALLOWLIST_OFFENDER],
        subject="fix(x): something",
        github_integrated=False,
    ), "github_integrated=False 且出界文件必须判红"


def test_check_scope_exempts_bootstrap() -> None:
    """bootstrap 豁免（仓库最初提交 / --bootstrap）：整树入仓也不算违规。"""
    module = _load_master_scope_module()
    files = ["delector/server.py", "package_windows.py", "tests/test_x.py"]
    assert module.check_scope(files, subject="Initial commit", bootstrap=True) == []


def test_scope_script_pins_exact_allowlist() -> None:
    """白名单 MUST 含审计 P1-1 的 8 项，且 MUST NOT 出现放行一切的通配。"""
    module = _load_master_scope_module()
    required = (
        "WORKMEMORY/",
        "docs/",
        "README.md",
        "CHANGELOG.md",
        "static/index.html",
        "static/sw.js",
        "android/app/build.gradle",
        "delector/core/version.py",
    )
    for entry in required:
        assert entry in module.MASTER_DIRECT_ALLOWLIST, f"白名单缺 {entry!r}"
    for wildcard in ("**", "*"):
        assert wildcard not in module.MASTER_DIRECT_ALLOWLIST, (
            f"白名单出现 {wildcard!r}：会放行一切，机械闸形同虚设"
        )


def test_cli_exit_code_pass_is_zero() -> None:
    """退出码 0 = 通过（全部提交 ⊆ 白名单）。"""
    module = _load_master_scope_module()
    git = _FakeGit({"c1": _FakeCommit("docs: ok", ("docs/a.md", "WORKMEMORY/work.log"))})
    assert module.main(["--range", "aaa..bbb"], git=git) == 0


def test_cli_exit_code_violation_is_one(capsys: pytest.CaptureFixture[str]) -> None:
    """退出码 1 = 有违规，且 stderr 打出「sha + 出界文件」。"""
    module = _load_master_scope_module()
    git = _FakeGit({"c1": _FakeCommit("feat: 越界", (_ALLOWLIST_OFFENDER, "docs/a.md"))})
    assert module.main(["--range", "aaa..bbb"], git=git) == 1
    err = capsys.readouterr().err
    assert "c1" in err and _ALLOWLIST_OFFENDER in err


def test_cli_exempts_github_squash_merge(capsys: pytest.CaptureFixture[str]) -> None:
    """A squash 形（单父 + committer GitHub + subject 带 (#NNN) + 出界文件）⇒ exit 0 且 stderr 打出豁免。"""
    module = _load_master_scope_module()
    git = _FakeGit(
        {
            "c_squash": _FakeCommit(
                subject="fix(probe): stop running the vm layer after the static layer already failed (#166)",
                files=(_ALLOWLIST_OFFENDER,),
                committer_name="GitHub",
                committer_email="noreply@github.com",
                parents=("parent1",),
            )
        }
    )
    assert module.main(["--range", "aaa..bbb"], git=git) == 0
    err = capsys.readouterr().err
    assert "c_squash" in err and "GitHub" in err and "noreply@github.com" in err


def test_cli_exempts_github_dependabot_merge(capsys: pytest.CaptureFixture[str]) -> None:
    """B Dependabot 形（单父 + committer GitHub + subject 不带 (#NNN) + 出界文件）⇒ exit 0。证明非按标题判。"""
    module = _load_master_scope_module()
    git = _FakeGit(
        {
            "c_dep": _FakeCommit(
                subject="bump foo from 1.0.0 to 1.0.1",
                files=(_ALLOWLIST_OFFENDER,),
                committer_name="GitHub",
                committer_email="noreply@github.com",
                parents=("parent1",),
            )
        }
    )
    assert module.main(["--range", "aaa..bbb"], git=git) == 0
    err = capsys.readouterr().err
    assert "c_dep" in err and "GitHub" in err


def test_cli_flags_human_direct_push_violation(capsys: pytest.CaptureFixture[str]) -> None:
    """C 人类单父直推 + 出界文件 ⇒ exit 1。"""
    module = _load_master_scope_module()
    git = _FakeGit(
        {
            "c_human": _FakeCommit(
                subject="feat(client): direct push to master",
                files=(_ALLOWLIST_OFFENDER,),
                committer_name="Developer",
                committer_email="dev@example.com",
                parents=("parent1",),
            )
        }
    )
    assert module.main(["--range", "aaa..bbb"], git=git) == 1
    err = capsys.readouterr().err
    assert "c_human" in err and _ALLOWLIST_OFFENDER in err


def test_cli_rejects_merge_subject_spoof(capsys: pytest.CaptureFixture[str]) -> None:
    """D 伪造：subject 'Merge pull request #1 from evil' + 单父 + 人类 committer + 出界文件 ⇒ exit 1。"""
    module = _load_master_scope_module()
    git = _FakeGit(
        {
            "c_spoof": _FakeCommit(
                subject="Merge pull request #1 from evil",
                files=(_ALLOWLIST_OFFENDER,),
                committer_name="Attacker",
                committer_email="attacker@example.com",
                parents=("parent1",),
            )
        }
    )
    assert module.main(["--range", "aaa..bbb"], git=git) == 1
    err = capsys.readouterr().err
    assert "c_spoof" in err and _ALLOWLIST_OFFENDER in err


def test_cli_exit_code_environment_unavailable_is_two(capsys: pytest.CaptureFixture[str]) -> None:
    """退出码 2 = 环境不可用（git 调用失败）。"""
    module = _load_master_scope_module()

    def broken_git(args: Sequence[str]) -> str:
        raise module.GitError("not a git repository")

    assert module.main(["--range", "aaa..bbb"], git=broken_git) == 2
    assert "环境不可用" in capsys.readouterr().err


def test_cli_undeterminable_range_warns_through(capsys: pytest.CaptureFixture[str]) -> None:
    """范围不可判定（before 全零 = 首次推送）⇒ 显式警告后通过，禁止静默。"""
    module = _load_master_scope_module()
    git = _FakeGit({"c1": _FakeCommit("feat: 越界", (_ALLOWLIST_OFFENDER,))})
    assert module.main(["--range", f"{_ZERO_SHA}..bbb"], git=git) == 0
    err = capsys.readouterr().err
    assert "不可判定" in err and "首次推送" in err, "首次推送范围必须**显式警告后**通过，禁止静默"


def test_cli_bootstrap_flag_skips_with_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """显式 --bootstrap ⇒ 跳过范围检查，但 MUST 打印警告（不静默）。"""
    module = _load_master_scope_module()
    git = _FakeGit({"c1": _FakeCommit("feat: 越界", (_ALLOWLIST_OFFENDER,))})
    assert module.main(["--range", "aaa..bbb", "--bootstrap"], git=git) == 0
    assert "bootstrap" in capsys.readouterr().err.lower()


def test_cli_root_commit_is_bootstrap_exempt(capsys: pytest.CaptureFixture[str]) -> None:
    """仓库最初提交（root commit）⇒ 自动 bootstrap 豁免，不判红。"""
    module = _load_master_scope_module()
    git = _FakeGit({"root1": _FakeCommit("Initial commit", ("delector/server.py",), is_root=True)})
    assert module.main(["--range", "aaa..bbb"], git=git) == 0
    assert "最初提交" in capsys.readouterr().err


def test_cli_restricts_range_to_first_parent_mainline() -> None:
    """范围遍历 MUST 只取 mainline（--first-parent）——否则 PR 合并带入的分支提交会被误判违规。

    实测（本机，2026-10-16）：PR #139 合并提交 dac3a8b 在 CI 口径范围 dac3a8b^1..dac3a8b 下，
    仅 --no-merges 得 20 个提交、加 --first-parent 得 0 个。缺 --first-parent 会让本闸在每次
    正常 PR 合并时把 master 推红（P1-1 要消灭的失败形态）。
    """
    module = _load_master_scope_module()
    git = _FakeGit({"c1": _FakeCommit("docs: ok", ("docs/a.md",))})
    assert module.main(["--range", "aaa..bbb"], git=git) == 0
    revlist_calls = [call for call in git.calls if call and call[0] == "rev-list" and "--no-merges" in call]
    assert revlist_calls, "未观察到 rev-list 调用"
    assert all("--first-parent" in call for call in revlist_calls), (
        f"范围遍历缺 --first-parent：{revlist_calls} —— PR 合并会被误判为直推违规、把 master 推红"
    )


def test_commit_files_uses_nul_separated_output_to_survive_non_ascii_paths() -> None:
    """改动面 MUST 用 ``-z``（NUL 分隔）读取，且非 ASCII 路径仍命中白名单。

    实测（本机，2026-10-16）：git 默认 ``core.quotePath=true``，含中文的路径会被输出成
    ``"WORKMEMORY/notes/NOTES-…\\345\\206\\205….md"``（**带引号 + 八进制转义**）⇒ 前缀规则
    因开头多一个 ``"`` 匹配不上 ⇒ **假阳性**（把合法的簿记推送判成违规、拦下推送）。
    本用例把两条都钉住：① 取文件的命令带 ``-z``；② 非 ASCII 路径仍被判为白名单内。
    """
    module = _load_master_scope_module()
    captured: list[list[str]] = []

    def _recording_git(args: list[str]) -> str:
        captured.append(list(args))
        if args and args[0] == "diff-tree":
            # 模拟 -z 输出：NUL 分隔、不做引号转义（含中文路径原样返回）
            return "\x00".join(
                [
                    "WORKMEMORY/notes/NOTES-2026-10-05-0030-done-技术债清理.md",
                    "WORKMEMORY/INDEX.md",
                ]
            )
        return "c1"

    files = module._commit_files(_recording_git, "c1")
    assert any("\u6280\u672f\u503a" in path for path in files), f"非 ASCII 路径未被解析出来：{files}"
    assert not any(path.startswith('"') for path in files), f"路径仍带引号（被 quotePath 转义了）：{files}"
    diff_calls = [call for call in captured if call and call[0] == "diff-tree"]
    assert diff_calls, "未观察到 diff-tree 调用"
    assert all("-z" in call for call in diff_calls), (
        f"取改动面缺 -z：{diff_calls} —— 中文路径会被 quotePath 转义成 \"…\\345…\"，前缀规则匹配不上 ⇒ 假阳性"
    )
    assert module.check_scope(files, subject="docs: 收拢笔记") == []


def test_pre_push_hook_targets_master_and_prints_skip_reason() -> None:
    """pre-push 必须针对 refs/heads/master 判定，且不适用的情形明确打印跳过原因。"""
    text = _read_guard_file(PRE_PUSH_HOOK)
    assert "/usr/bin/env bash" in text, "pre-push 缺 bash shebang"
    assert "refs/heads/master" in text, "pre-push 未针对 refs/heads/master 判定"
    assert "tools/check_master_commit_scope.py" in text, "pre-push 未接线判定器"
    assert "跳过" in text, "pre-push 不适用的情形 MUST 明确打印跳过原因（禁止静默通过）"


def test_ci_workflow_has_master_direct_push_scope_job() -> None:
    """ci.yml 必须有「仅 push→master」触发的直推范围 gate job，并以 before..sha 调用判定器。"""
    text = _read_guard_file(CI_WORKFLOW)
    assert "master-direct-push-scope:" in text, f"{CI_WORKFLOW} 缺 master 直推范围 gate job"
    block = _job_block(CI_WORKFLOW, "master-direct-push-scope")
    assert "github.event_name == 'push'" in block, "job 未限定为 push 事件（PR 无 before..sha 语义）"
    assert "github.event.before" in block and "github.sha" in block, (
        "job 未以 before..sha 为范围调用判定器"
    )
    assert "tools/check_master_commit_scope.py" in block, "job 未接线判定器"
    assert "fetch-depth: 0" in block, (
        "job 的 checkout 未取全历史：before 基线不在本地对象库 ⇒ git 取不到范围"
        "（与 master push 红事故同因）"
    )


# ── pytest 分片完整性/配平守卫（2026-11-04，关键路径压缩）────────────────────────
# 背景：旧 matrix 写 `tests/test_[a-c]*.py --ignore=...`。bash 会先把 glob 展开成
# **显式文件路径**，而 pytest 的 `--ignore` 只作用于目录递归 ⇒ 被 ignore 的文件照跑。
# 实测（run 41793803081）unit-1 因此 721 passed（按意图应为 608），unit-2 / unit-4
# 同样重复执行 cost/integration 子集：分片既不完整也不互斥，还白烧 runner 时间。
# 现分片成员集中在 tools/ci_shards.py（唯一事实来源），下面四条钉住：
#   ① 全部 tests/test_*.py 恰好出现在一个分片（新增文件必须显式归位）；
#   ② 专项分片（cost-guards / integration-heavy）不被普通分片重复收录；
#   ③ 四个 unit 分片按实测时长配平（unit-2 另扣静态门禁 14s）；
#   ④ workflow 不得退回 glob + --ignore 写法（那是本轮要修的根因）。

CI_SHARDS_TOOL = REPO_ROOT / "tools" / "ci_shards.py"
CI_SHARD_WEIGHTS = REPO_ROOT / "tools" / "ci_shard_weights.json"

COST_GUARD_TESTS = frozenset(
    {
        "tests/test_articles_list_cost.py",
        "tests/test_cards_endpoint_cost.py",
        "tests/test_cold_start_cost.py",
    }
)
INTEGRATION_TESTS = frozenset(
    {
        "tests/test_bench_judge_gaming.py",
        "tests/test_frontend_layers.py",
        "tests/test_server.py",
        "tests/test_server_settings_security.py",
        "tests/test_syntax_hard_api.py",
    }
)
# cost 专项分片拆成两个独立 runner（TODO-CI-04）：每个分片仍只含 cost 文件，
# 没有 xdist、也不与普通测试共享进程。两个分片的并集必须恰好覆盖 COST_GUARD_TESTS。
UNIT_SHARDS = ("unit-1", "unit-2", "unit-3", "unit-4")
# unit-2 额外执行 6 个 Ruff/mypy 步骤；PR #210 实测约 14s（六步合计）
STATIC_GATE_STEP_SECONDS = 14.0


def _load_shard_plan() -> Any:
    """按文件路径加载 tools/ci_shards.py（tools 不是包，避免依赖 sys.path 形状）。"""
    spec = importlib.util.spec_from_file_location("ci_shards_plan", CI_SHARDS_TOOL)
    assert spec is not None and spec.loader is not None, f"无法加载分片计划：{CI_SHARDS_TOOL}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_shards_partition_every_test_file_exactly_once() -> None:
    """全部 tests/test_*.py 必须恰好被一个分片收录；matrix 名称与计划一致。"""
    plan = _load_shard_plan()
    all_tests = {p.relative_to(REPO_ROOT).as_posix() for p in REPO_ROOT.glob("tests/test_*.py")}

    counts: Counter[str] = Counter()
    for shard in plan.SHARDS:
        for test_file in plan.resolve_shard(shard):
            counts[test_file] += 1

    duplicated = sorted(f for f, n in counts.items() if n > 1)
    missing = sorted(all_tests - set(counts))
    unknown = sorted(set(counts) - all_tests)
    assert not duplicated, (
        "以下测试文件被多个分片重复执行（runner 时间翻倍且互相掩盖失败）：\n"
        + "\n".join(duplicated)
    )
    assert not missing, (
        "以下测试文件没有被任何分片执行（漏测）：\n"
        + "\n".join(missing)
        + "\n新增 tests/test_*.py 后，请把它加入 tools/ci_shards.py 的对应分片。"
    )
    assert not unknown, (
        "分片计划列出了不存在的测试文件：\n" + "\n".join(unknown)
    )

    matrix_names = re.findall(r"^\s*- name:\s*(\S+)\s*$", _ci_job_block("ci"), re.MULTILINE)
    assert set(matrix_names) == set(plan.SHARDS), (
        "ci.yml 的 matrix 分片名与 tools/ci_shards.py 不一致："
        f"matrix={sorted(matrix_names)}，plan={sorted(plan.SHARDS)}"
    )


def test_ci_shards_keep_dedicated_suites_isolated() -> None:
    """cost 专项分片（2 个）/ integration-heavy 的成员必须独占，不能被普通分片重复收录。"""
    plan = _load_shard_plan()

    missing_cost_shards = sorted(set(COST_GUARD_SHARDS) - set(plan.SHARDS))
    assert not missing_cost_shards, (
        f"缺少 cost 专项分片 {missing_cost_shards}：cost 门禁被并回普通分片（或分片被删），"
        "计时断言会与无关测试共享进程。修法：在 tools/ci_shards.py 恢复 "
        f"{sorted(COST_GUARD_SHARDS)} 两个分片。"
    )
    cost_union: set[str] = set()
    for shard in COST_GUARD_SHARDS:
        members = set(plan.resolve_shard(shard))
        assert members, f"{shard} 分片为空：cost 门禁会静默消失"
        non_cost = sorted(members - COST_GUARD_TESTS)
        assert not non_cost, (
            f"{shard} 混入了非 cost 文件 {non_cost}：计时断言必须留在**只含 cost 文件**"
            "的专项分片里，不得与普通测试共享进程"
        )
        cost_union |= members
    assert cost_union == COST_GUARD_TESTS, (
        "两个 cost 分片的并集必须恰好覆盖 " + "、".join(sorted(COST_GUARD_TESTS))
        + f"，实际覆盖 {sorted(cost_union)}（重复或漏项都会让成本门禁失真）"
    )
    assert set(plan.resolve_shard("integration-heavy")) == INTEGRATION_TESTS, (
        "integration-heavy 分片的成员被改动：它必须恰好覆盖 " + "、".join(sorted(INTEGRATION_TESTS))
    )
    for shard in UNIT_SHARDS:
        overlap = set(plan.resolve_shard(shard)) & (COST_GUARD_TESTS | INTEGRATION_TESTS)
        assert not overlap, (
            f"{shard} 重复收录了专项分片的用例 {sorted(overlap)}："
            "这会让慢用例跑两遍，把该分片重新顶成关键路径"
        )


def test_ci_shards_are_balanced_by_measured_duration() -> None:
    """四个 unit 分片的实测时长（含 unit-2 静态门禁）必须落在均值 ±25% 内。"""
    plan = _load_shard_plan()
    weights = json.loads(CI_SHARD_WEIGHTS.read_text(encoding="utf-8"))

    effective = {}
    for shard in UNIT_SHARDS:
        total = sum(weights.get(f, 0.1) for f in plan.resolve_shard(shard))
        if shard == "unit-2":
            total += STATIC_GATE_STEP_SECONDS
        effective[shard] = total

    mean = sum(effective.values()) / len(effective)
    low, high = mean * 0.75, mean * 1.25
    outliers = {s: round(v, 1) for s, v in effective.items() if not (low <= v <= high)}
    assert not outliers, (
        "unit 分片负载失衡（单位：本机实测秒，unit-2 已加静态门禁 "
        f"{STATIC_GATE_STEP_SECONDS:g}s）：{outliers}；均值 {mean:.1f}s，允许 "
        f"{low:.1f}–{high:.1f}s。请按实测时长重新分配 tools/ci_shards.py，"
        "并更新 tools/ci_shard_weights.json。"
    )


def test_ci_workflow_runs_explicit_shard_plan() -> None:
    """ci.yml 必须调用分片计划；不得退回 glob + `--ignore`（根因是 --ignore 对显式文件无效）。"""
    text = _read_guard_file(CI_WORKFLOW)

    assert "tools/ci_shards.py" in text, "ci.yml 未调用 tools/ci_shards.py 的分片计划"
    assert "${{ matrix.suite.args }}" not in text, "ci.yml 仍在用 matrix.suite.args（应改用显式清单）"
    assert "tests/test_[a-c]*.py" not in text, (
        "ci.yml 出现了 glob 分片写法：bash 展开后 `--ignore` 对显式文件无效，"
        "会重新引入重复执行（旧 unit-1 实测 721 passed，意图 608）"
    )
    assert "pytest -q $(python tools/ci_shards.py ${{ matrix.suite.name }})" in text, (
        "pytest 步骤必须按 matrix.suite.name 取显式清单"
    )


# ── Android 本机配置隔离（2026-11-04）─────────────────────────────────────────
# 背景：`android/app/build.gradle` 一度被写死本机 Python 的 Windows 绝对路径
# （C:\Users\...\python.exe）。ci.yml 里没有 gradle 步骤 ⇒ PR 全绿；但
# build-release.yml 与 android-emulator.yml 的 Ubuntu runner 不存在该路径，
# 于是"PR 绿、发版日炸"。本机解释器改放 android/local.properties 的可选键
# python.buildPython（该文件已被 .gitignore 忽略，不会入库）。

ROOT_GITIGNORE = REPO_ROOT / ".gitignore"

# 同时用真实 git 语义校验忽略规则：文件不存在时 check-ignore 仍按规则匹配。
LOCAL_ONLY_ANDROID_PATHS = (
    "android/local.properties",
    "android/.idea/gradle.xml",
)

# 盘符绝对路径：C:\Users\... 或 D:/Android/... 之类。前置断言排除 https://
# 这类带字母前缀的伪匹配（"s:/" 前是字母，不入选）。
_DRIVE_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


def test_android_build_gradle_has_no_machine_absolute_paths() -> None:
    """build.gradle 不得含任何机器绝对路径，buildPython 也不得写字符串字面量。"""
    text = _read_guard_file(ANDROID_APP_BUILD_GRADLE)

    offenders = [
        f"{lineno}: {line.strip()}"
        for lineno, line in enumerate(text.splitlines(), 1)
        if _DRIVE_ABSOLUTE_PATH.search(line)
    ]
    assert not offenders, (
        "android/app/build.gradle 出现机器绝对路径（盘符路径）：\n"
        + "\n".join(offenders)
        + "\nUbuntu runner 上不存在该路径，build-release.yml / android-emulator.yml 的 "
        "gradle 构建会失败，而 ci.yml 不含 gradle 步骤 ⇒ PR 仍然全绿。"
        "本机解释器请写进 android/local.properties 的 python.buildPython 键。"
    )

    # 即便路径不是盘符形式，buildPython 也不许写字符串字面量：
    # 只能来自 local.properties 的变量，否则换一台机器就不可复现。
    assert not re.search(r"buildPython\s+[\"']", text), (
        "android/app/build.gradle 的 buildPython 写成了字符串字面量；"
        "它必须来自 android/local.properties 的 python.buildPython 键（文件缺失时保持不设置）。"
    )


def test_local_only_android_files_are_gitignored() -> None:
    """.idea/、local.properties、*.iml 必须被根 .gitignore 忽略（含 git 语义复核）。"""
    text = _read_guard_file(ROOT_GITIGNORE)
    rules = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    required = {"android/.idea/", "android/local.properties", "*.iml"}
    missing = required - rules
    assert not missing, (
        f".gitignore 缺少本机专属 Android 文件的忽略规则：{sorted(missing)}。"
        "android/local.properties 含 sdk.dir 绝对路径、android/.idea/ 是 IDE 本地状态，"
        "一次 `git add -A` 就会把它们提交进历史。"
    )

    for path in LOCAL_ONLY_ANDROID_PATHS:
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"git check-ignore 判定 {path} 未被忽略（exit {result.returncode}）："
            "本机 SDK 绝对路径 / IDE 状态会被误提交。"
        )
