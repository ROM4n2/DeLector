# -*- coding: utf-8 -*-
"""master 直推范围的机械闸（审计 P1-1：分支纪律此前没有机械闸）。

为什么存在
----------
``docs/reviews/2026-10-16-commit-rhythm-and-git-management-audit.md`` 的 P1-1：
2026-10-09~14 有 25 个 feat/fix/ci/test/perf 提交**直推 master**（含生产代码与 CI 定义），
且已实发事故 —— ``f49d359 fix(ci): 修 master push 上 CI 变红``（一次直推把 master 推红后
才回头补）。规则 2026-10-14 才写进可见文档，此前 agent 按 AGENTS.md bootstrap 根本读不到。
本脚本把「master 上**非 merge** 提交的改动面 MUST ⊆ 白名单」做成**可测的判定器**，
供 ① ``.githooks/pre-push`` 与 ② CI job 两道接线共用。

判定规则
--------
对范围内每个 **mainline 非 merge** 提交（``rev-list --no-merges --first-parent``）：其改动面
MUST ⊆ ``MASTER_DIRECT_ALLOWLIST``（簿记 + 文档 + 版本面）；否则**该 sha 违规**，打印
「sha + 出界文件 + 命中规则」。（为什么必须带 ``--first-parent``：见 ``_list_commits`` ——
不加会把每次 PR 合并的分支提交误判为直推违规。）

三条豁免出口（**绝不静默**，一律打印明确警告/信息后再通过）：
1. **bootstrap** —— 仓库最初的提交（root commit）或显式 ``--bootstrap``：历史回溯 / 首次
   导入时整树入仓，若不豁免会全红。
2. **范围不可判定** —— 首次推送（``before`` 全零 / 为空）时范围无从谈起。
3. **GitHub 集成 PR 合并** —— GitHub 网页/集成合并的提交（committer == ``GitHub <noreply@github.com>``）。
   覆盖 squash 与 rebase 方式合并进 master 的单父 mainline 提交。

实测数据支撑与可伪造局限说明
----------------------------
master 历史 1315 提交实测（committer 干净二分）：
- committer == ``GitHub <noreply@github.com>``：180 条（154 条 ≥2 父的 merge commit，
  26 条单父 squash/rebase 提交）。其中 24 条无 ``(#NNN)`` 标题后缀（Dependabot 依赖升级）。
  按 committer 身份判定可覆盖全部 26 条；若仅按标题正则判会漏掉 24/26 = 92%。
- committer == 人类：1135 条（1113 条单父直推审查对象，22 条多父 merge）。人类单父中标题以
  ``Merge `` 开头者为 0 条。

⚠️ 诚实局限说明：
committer 身份完全由 git 客户端设定，操作者可用
``GIT_COMMITTER_NAME=GitHub GIT_COMMITTER_EMAIL=noreply@github.com``
在本地伪造身份绕过本闸。本闸的目标是防御**事故类直推**（习惯性或无意识的直推 —— 如审计 P1-1
指出的 25 个包含生产代码的直推提交，且曾引发 f49d359 事故），而非防范蓄意内鬼攻击。
豁免一律在大声打印（stderr 打出 sha、committer 姓名与邮箱），因而代码审查与审计日志完全可见，
这是本方案被接受的理由，**不是**其不可伪造的证明。
另外，rebase 型合并覆盖是按 committer 身份**构造性成立**（那 24 条无 ``(#NNN)`` 的
Dependabot 样本是它的经验面），**不是**实测到一次手写代码的 rebase 合并。

⚠️ 纪律（计划 Global Constraints）：机械闸 MUST **fail-loud 且可解释**，MUST NOT 出现
「拦不住真实情况却让人以为拦住了」—— 故任何豁免都在 stdout/stderr 留下明确字样。

退出码
------
0 = 通过（含三条豁免的 warn-through）；1 = 有违规；2 = 环境不可用（git 不可用 / 不是
仓库 / 范围无法解析等）。照 ``tools/bench_judge_fp.py`` 的 0/1/2 惯例。

只读：仅调用 ``git rev-list`` / ``git log`` / ``git diff-tree``（全只读）。
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import re
import subprocess
import sys
from typing import Callable, NamedTuple, Optional, Sequence, TextIO

#: master 直推白名单：簿记 + 文档 + 版本面（与审计 P1-1 的建议清单逐项一致）。
#: 语义：以 ``/`` 结尾 = 目录前缀；否则 = 精确文件名（亦接受 ``*`` 通配 —— 便于用 ``**``
#: 表达「放行一切」，且该写法会被 tests/test_ci_hardening.py 的守卫**显式抓红**）。
MASTER_DIRECT_ALLOWLIST: tuple[str, ...] = (
    "WORKMEMORY/",
    "docs/",
    "README.md",
    "CHANGELOG.md",
    "static/index.html",
    "static/sw.js",
    "android/app/build.gradle",
    "delector/core/version.py",
)

#: git 调用超时（秒）：新增进程链 MUST 有界（计划「进程纪律」）。
GIT_TIMEOUT_SECONDS = 60

#: GitHub 集成合并（网页 PR merge/squash/rebase）盖戳的 committer 身份。
GITHUB_COMMITTER_NAME = "GitHub"
GITHUB_COMMITTER_EMAIL = "noreply@github.com"

#: 合并提交 subject 形态。CLI 已用 ``git rev-list --no-merges`` 过滤，这里做纵深防御
#: （并让「合并提交豁免」在纯函数层可单测 —— 计划 Step 4 变异自证要求删豁免即红）。
_MERGE_SUBJECT_RE = re.compile(
    r"^Merge (?:pull request #\d+|branch '|remote-tracking branch '|tag '|commit )"
)


def _is_github_integrated(committer_name: str, committer_email: str) -> bool:
    """判断 committer 是否为 GitHub 集成操作（网页 squash / rebase / merge）。

    姓名精确匹配 "GitHub"，邮箱大小写不敏感匹配 "noreply@github.com"。
    """
    return (
        committer_name == GITHUB_COMMITTER_NAME
        and committer_email.strip().lower() == GITHUB_COMMITTER_EMAIL.lower()
    )


class GitError(RuntimeError):
    """git 调用失败（命令缺失 / 非零退出 / 超时）⇒ CLI 退出码 2。"""


#: git 运行器协议：接收参数列表（不含前导 ``git``），返回 stdout 文本。
GitRunner = Callable[[Sequence[str]], str]


def _is_all_zero(rev: str) -> bool:
    """revision 是否为空或全零（首次推送的 ``before``）。"""
    stripped = rev.strip()
    return stripped == "" or set(stripped) == {"0"}


def _is_merge_subject(subject: str) -> bool:
    """subject 是否属于合并提交（纵深防御：CLI 另有 ``--no-merges``）。"""
    return bool(_MERGE_SUBJECT_RE.match(subject.strip()))


def _is_allowed(path: str, allowlist: Sequence[str] = MASTER_DIRECT_ALLOWLIST) -> bool:
    """单个路径是否落在白名单内（目录前缀 or 精确名 / 通配）。"""
    for rule in allowlist:
        if rule.endswith("/"):
            if path == rule[:-1] or path.startswith(rule):
                return True
        elif fnmatch.fnmatchcase(path, rule):
            return True
    return False


def check_scope(
    changed_files: Sequence[str],
    *,
    subject: str,
    bootstrap: bool = False,
    github_integrated: bool = False,
    is_merge_commit: bool = False,
) -> list[str]:
    """判定单个提交的改动面是否越界；返回违规原因列表（空 = 通过）。

    豁免次序：
    1. ``bootstrap=True``：仓库最初提交或显式声明 bootstrap（整树入仓，豁免）。
    2. ``github_integrated=True``：GitHub 集成 PR 合并（committer 为 GitHub <noreply@github.com>）。
    3. ``_is_merge_subject(subject) and is_merge_commit``：真实合并提交（≥2 父）且标题符合 merge 格式。
       ⚠️ 必须同时满足 is_merge_commit，关闭单父伪造 merge 标题绕过检查的路径。
    """
    if bootstrap:
        return []
    if github_integrated:
        return []
    if _is_merge_subject(subject) and is_merge_commit:
        return []
    allowlist_summary = " · ".join(MASTER_DIRECT_ALLOWLIST)
    reasons: list[str] = []
    for raw in changed_files:
        path = raw.strip()
        if not path:
            continue
        if not _is_allowed(path):
            reasons.append(
                f"出界文件 {path!r}：master 直推改动面 MUST ⊆ 白名单"
                f"（{allowlist_summary}），但未命中任何规则"
            )
    return reasons


def _default_git(args: Sequence[str]) -> str:
    """默认 git 运行器（只读命令）：返回 stdout；失败 / 超时抛 ``GitError``。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitError(f"找不到 git 可执行文件：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} 超时（>{GIT_TIMEOUT_SECONDS}s）") from exc
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 退出码 {proc.returncode}：{proc.stderr.strip()}")
    return proc.stdout


def _list_commits(git: GitRunner, range_spec: str) -> list[str]:
    """范围内的 **mainline** 非 merge 提交（``rev-list --no-merges --first-parent``）。

    为什么在计划的 ``--no-merges`` 之外 MUST 再加 ``--first-parent``：
    只用 ``--no-merges`` 时，范围一旦跨过 merge 提交，``rev-list`` 会把**被合并分支的
    全部提交**也纳入（它们从 merge 的第二父可达）—— 实测（本机，2026-10-16）：PR #139 的
    合并提交 ``dac3a8b``（父 ``40d8f18``/``30b0e12``）在 CI 口径范围 ``dac3a8b^1..dac3a8b``
    下 ``--no-merges`` 得 **20** 个提交、加 ``--first-parent`` 得 **0** 个。若不加
    ``--first-parent``，本闸会在**每次正常 PR 合并**时把该 PR 的分支提交判成「直推违规」而
    把 master 推红 —— 正是 P1-1 要消灭的失败形态（f49d359 事故同族）。
    审计 P1-1 的实测复核本身用的就是 ``--first-parent --no-merges master``，本实现与其口径一致。
    """
    out = git(["rev-list", "--no-merges", "--first-parent", range_spec])
    return [line.strip() for line in out.splitlines() if line.strip()]


class CommitMeta(NamedTuple):
    """单条提交的元数据（进程纪律：一次 git log 获取全部字段）。"""

    subject: str
    committer_name: str
    committer_email: str
    parents: tuple[str, ...]

    @property
    def is_root(self) -> bool:
        """是否为仓库最初提交（0 父）。"""
        return len(self.parents) == 0

    @property
    def is_merge_commit(self) -> bool:
        """是否为合并提交（≥2 父）。"""
        return len(self.parents) >= 2


def _commit_meta(git: GitRunner, sha: str) -> CommitMeta:
    """一次 git log 获取提交的 subject / committer / parents。

    分隔符 MUST 用 ``%x00``（NUL），防止非 ASCII subject / committer 姓名挤错位。
    """
    raw = git(["log", "-1", "--format=%s%x00%cn%x00%ce%x00%P", sha])
    lines = raw.splitlines()
    line = lines[0] if lines else ""
    parts = line.split("\x00")
    subject = parts[0] if len(parts) > 0 else ""
    committer_name = parts[1] if len(parts) > 1 else ""
    committer_email = parts[2] if len(parts) > 2 else ""
    parents_raw = parts[3] if len(parts) > 3 else ""
    parents = tuple(parents_raw.split()) if parents_raw.strip() else ()
    return CommitMeta(
        subject=subject,
        committer_name=committer_name,
        committer_email=committer_email,
        parents=parents,
    )


def _commit_subject(git: GitRunner, sha: str) -> str:
    """单条提交的 subject（兼容保留）。"""
    return _commit_meta(git, sha).subject


def _commit_files(git: GitRunner, sha: str) -> list[str]:
    """单条提交的改动面（``git diff-tree --no-commit-id --name-only -r -z``）。

    ⚠️ **MUST 用 ``-z``**：git 默认 ``core.quotePath=true``，会把含**非 ASCII**的路径输出成
    ``"WORKMEMORY/notes/NOTES-…\\345\\206\\205….md"`` 这种**带引号 + 八进制转义**的形式，
    于是前缀规则（``WORKMEMORY/``）因开头多了一个 ``"`` 而**匹配不上** ⇒ 把合法的簿记推送
    判成违规（**假阳性**）。2026-10-16 实测踩到：把 7 份中文文件名的 ``NOTES-*`` 收拢进
    ``WORKMEMORY/notes/`` 时，本闸正确地**拦下了自己的主人**，但拦错了。
    ``-z`` 用 NUL 分隔且**完全不做引号转义**，同时也能容纳路径里含换行的极端情况。
    """
    out = git(["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha])
    return [path for path in out.split("\x00") if path.strip()]


def _is_root_commit(git: GitRunner, sha: str) -> bool:
    """root commit 判定（兼容保留）。"""
    return _commit_meta(git, sha).is_root


def _range_before(range_spec: str) -> Optional[str]:
    """取出 ``A..B`` 的 ``A``（空串归一为 None）；无 ``..`` 视为调用错误。"""
    if ".." not in range_spec:
        raise ValueError(f"非法 --range {range_spec!r}：期望 `<from>..<to>` 形式")
    before, _, _after = range_spec.partition("..")
    before = before.strip()
    return before or None


def run_check(
    range_spec: str,
    *,
    bootstrap: bool = False,
    git: Optional[GitRunner] = None,
    out: Optional[TextIO] = None,
    err: Optional[TextIO] = None,
) -> int:
    """核心判定：返回退出码（0/1/2）。豁免一律**显式打印**（绝不静默）。"""
    runner: GitRunner = _default_git if git is None else git
    stdout: TextIO = sys.stdout if out is None else out
    stderr: TextIO = sys.stderr if err is None else err

    before = _range_before(range_spec)

    if bootstrap:
        print(
            f"[master-commit-scope] 警告：--bootstrap 已启用 ⇒ 范围检查整体跳过"
            f"（范围 {range_spec!r}）。bootstrap 仅用于历史回溯 / 首次导入，"
            f"**不代表该范围合规**。",
            file=stderr,
        )
        return 0

    if before is None or _is_all_zero(before):
        print(
            f"[master-commit-scope] 警告：范围不可判定（{range_spec!r}：before 为空 / 全零 = "
            f"首次推送）⇒ 跳过范围检查（warn-through，绝不静默）。",
            file=stderr,
        )
        return 0

    try:
        shas = _list_commits(runner, range_spec)
    except GitError as exc:
        print(f"[master-commit-scope] 环境不可用：{exc}", file=stderr)
        return 2

    violations: list[tuple[str, str, list[str]]] = []
    for sha in shas:
        try:
            meta = _commit_meta(runner, sha)
            files = _commit_files(runner, sha)
        except GitError as exc:
            print(f"[master-commit-scope] 环境不可用：{exc}", file=stderr)
            return 2
        if meta.is_root:
            print(
                f"[master-commit-scope] {sha} 是仓库最初提交（root commit）⇒ bootstrap 豁免"
                f"（整树入仓，非违规）。",
                file=stderr,
            )
            continue
        is_gh = _is_github_integrated(meta.committer_name, meta.committer_email)
        if is_gh:
            print(
                f"[master-commit-scope] {sha} committer 为 {meta.committer_name} <{meta.committer_email}>"
                f" ⇒ GitHub 集成 PR 合并（squash/rebase）豁免（非直推，已过 PR 门禁）。",
                file=stderr,
            )
        reasons = check_scope(
            files,
            subject=meta.subject,
            github_integrated=is_gh,
            is_merge_commit=meta.is_merge_commit,
        )
        if reasons:
            violations.append((sha, meta.subject, reasons))

    if not violations:
        print(
            f"[master-commit-scope] 通过：{len(shas)} 个非 merge 提交的改动面全部 ⊆ 白名单"
            f"（范围 {range_spec!r}）。",
            file=stdout,
        )
        return 0

    print(
        f"[master-commit-scope] 违规：{len(violations)} 个提交的改动面越出白名单"
        f"（范围 {range_spec!r}）：",
        file=stderr,
    )
    for sha, subject, reasons in violations:
        print(f"  - 违规 sha: {sha}", file=stderr)
        print(f"    提交标题: {subject}", file=stderr)
        print(
            f"    命中规则: master 直推范围 MUST ⊆ 白名单"
            f"（{' · '.join(MASTER_DIRECT_ALLOWLIST)}）",
            file=stderr,
        )
        for reason in reasons:
            print(f"    出界: {reason}", file=stderr)
    return 1


def main(argv: Optional[Sequence[str]] = None, *, git: Optional[GitRunner] = None) -> int:
    """CLI 入口。退出码：0=通过；1=有违规；2=环境不可用。"""
    stdout = sys.stdout
    if isinstance(stdout, io.TextIOWrapper):
        try:
            stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK：中文需 UTF-8
        # silent-ok: 仅显示层编码（流已关闭/不可重配置，如 pytest capture）——本闸判定与退出码不经过 stdout 编码
        except Exception:  # 已关闭 / 不可重配置的流（如 pytest capture）⇒ 保持原状
            pass

    parser = argparse.ArgumentParser(
        description="master 直推范围机械闸（审计 P1-1）：非 merge 提交的改动面 MUST ⊆ 白名单。"
    )
    parser.add_argument(
        "--range",
        dest="range_spec",
        required=True,
        metavar="FROM..TO",
        help="git 提交范围，如 origin/master~5..origin/master 或 <before>..<sha>"
        "（CI 用 github.event.before..github.sha）",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="显式声明本次是 bootstrap（仓库最初导入）⇒ 跳过范围检查（会打印警告）",
    )
    args = parser.parse_args(argv)

    try:
        return run_check(args.range_spec, bootstrap=args.bootstrap, git=git)
    except ValueError as exc:
        print(f"[master-commit-scope] 参数错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
