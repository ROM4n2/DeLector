# -*- coding: utf-8 -*-
"""发布链路与 CI 接线守卫：Windows 验包、打包面检测、前端门禁与超时护栏。"""

import re
import subprocess

import pytest
from _ci_hardening_support import (
    CI_WORKFLOW,
    COST_GUARD_SHARDS,
    REPO_ROOT,
    _ci_job_block,
    _ci_step_blocks,
    _job_block,
    _read_guard_file,
    _step_using,
    _steps_of,
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
    # 2026-11-08 补齐：Windows/Android 共同内嵌的前端资产
    "static/**",
    # build-release 的 build-android 打包面
    "android/**",
    # Android 打包前同步 static + delector 的唯一入口
    "tools/sync_android_sources.py",
    # 打包期重算/注入 asset-fingerprint 的模块
    "delector/core/assets_manifest.py",
    "tools/verify_windows_portable.py",
    ".github/workflows/build-release.yml",
)


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


# ── 前端跨边界门禁的 CI 接线守卫（ADR-0021「替代投资#3」，改口径版）───────────────
# 背景（实测结论）：ADR-0021 §6.1 原计划给 static/（33k 行前端）加类型检查，但实测
# 全量 `tsc --allowJs --checkJs` 共 219 条存量错误、其中 199 条是缺 DOM 声明的 TS2339
# **噪音** ⇒ 全量接线 = 永远红的噪音源（本仓有过门禁恒真/恒红教训）。改口径后接进
# ubuntu 质量闸两件：
#   ① 路由契约（主仪器，阻塞步）：用**真实** app.routes 校验 static/js 的真实 HTTP 调用；
#   ② API 边界窄口径 tsc（次仪器）：固定 typescript@5.6.3，只查 tsconfig.json 的显式
#      allowlist（逐个文件列出，非全量 glob）。
# 本节把「步存在」「步归属 ubuntu 的 ci job（不是别的 job）」「版本固定」「allowlist 非
# 全量」逐一钉死 —— 只断言字符串在场挡不住「把步挪去别的 job」这类归属漂移。

CONTRACT_SCRIPT = "tools/check_frontend_api_contract.py"
TSC_PIN = "typescript@5.6.3"
TSCONFIG = REPO_ROOT / "tsconfig.json"
API_TYPES_JS = REPO_ROOT / "static" / "js" / "api-types.js"
UPDATE_JS = REPO_ROOT / "static" / "js" / "update.js"


def test_frontend_route_contract_gate_in_ubuntu_ci_job() -> None:
    """路由契约步 MUST 存在于 ubuntu 的 `ci` job，且为阻塞步（归属断言，非全文在场）。"""
    block = _ci_job_block("ci")
    assert "runs-on: ubuntu-latest" in block, "ci job 必须在 ubuntu 上跑（门禁定位：纯 Python、快）"
    assert CONTRACT_SCRIPT in block, (
        f"{CI_WORKFLOW} 的 ci job 未接线路由契约检查（{CONTRACT_SCRIPT}）：\n"
        "ADR-0021 替代投资#3 的主仪器被摘，前端调未知端点将无人拦截。"
    )
    step = _step_using(block, CONTRACT_SCRIPT)
    assert "continue-on-error: true" not in step, (
        "路由契约步带了 continue-on-error: true ⇒ 契约失败不阻断，闸形同虚设。"
    )


def test_frontend_route_contract_gate_precedes_pytest() -> None:
    """路由契约步 MUST 早于全量 pytest（顺序断言，防被挪到 pytest 之后 / 别的 job）。"""
    block = _ci_job_block("ci")
    steps = _steps_of(block)
    contract_idx = next((i for i, s in enumerate(steps) if CONTRACT_SCRIPT in s), None)
    pytest_idx = next((i for i, s in enumerate(steps) if "pytest -q" in s), None)
    assert contract_idx is not None, "找不到路由契约步（归属断言见上一条）"
    assert pytest_idx is not None, "找不到全量 pytest 步"
    assert contract_idx < pytest_idx, (
        "路由契约步出现在全量 pytest 之后：先失败先反馈的顺序被破坏，且归属可疑。"
    )


def test_frontend_tsc_gate_pins_fixed_version_in_ci() -> None:
    """窄口径 tsc 步 MUST 存在且固定 typescript 版本（MUST NOT latest —— 不可复现）。"""
    block = _ci_job_block("ci")
    steps = _steps_of(block)
    tsc_steps = [s for s in steps if "tsc --noEmit" in s]
    assert tsc_steps, f"{CI_WORKFLOW} 的 ci job 未接线 tsc 类型检查步（次仪器被摘）。"
    assert any(TSC_PIN in s for s in tsc_steps), (
        f"tsc 步未固定 {TSC_PIN}（应 `npx -p {TSC_PIN} tsc --noEmit`）：浮动版本不可复现。"
    )
    assert not any("latest" in s for s in tsc_steps), "tsc 步不得用 typescript@latest（不可复现）。"


# ── 前端探针去重守卫（2026-11-05，TODO-CI-04）─────────────────────────────────
# 背景：4 条前端探针（路由契约 / index 同步 / 分层不变式 / tsc）原在 matrix 公共 steps，
# 6 个 pytest 分片各跑一遍。它们与分片用例集合无关，属纯重复：`cost-guards` 实测为此
# 多花 5s（直接落在关键路径上），六份累计约 30s。2026-11 收敛为只在一个分片执行。
#
# 注意 Node 安装**不能**一起去重：`conftest.py::pytest_sessionstart` 在 CI 下要求**每个**
# pytest job 都有 node（缺了直接 exit 1），故 setup-node 留在公共 steps。
FRONTEND_GATE_STEP_NAMES = (
    "Frontend API contract gate (routes)",
    "Frontend index.html template sync gate",
    "Frontend style.css source sync gate",
    "Frontend layer invariants gate",
    "Frontend API-boundary type gate (tsc)",
)


def test_frontend_gates_run_in_exactly_one_shard() -> None:
    """4 条前端探针必须只在一个分片执行，宿主分片真实存在且不是 cost 专项分片。"""
    steps = _ci_step_blocks()
    hosts: set[str] = set()

    for name in FRONTEND_GATE_STEP_NAMES:
        assert name in steps, (
            f"{CI_WORKFLOW} 缺少前端探针步骤 {name!r}：真实检查被删，不得用提速名义砍掉"
        )
        match = re.search(
            r"^\s*if:\s*matrix\.suite\.name\s*==\s*'([^']+)'\s*$",
            steps[name],
            re.MULTILINE,
        )
        assert match, (
            f"{name!r} 没有 `if: matrix.suite.name == '<分片>'` 守卫："
            "前端探针会重新落到六个分片各跑一遍（实测六份累计约 30s，"
            "其中 cost-guards 的 5s 直接压在关键路径上）"
        )
        hosts.add(match.group(1))

    assert len(hosts) == 1, f"4 条前端探针必须挂同一个分片，实际: {sorted(hosts)}"

    host = next(iter(hosts))
    matrix_names = re.findall(r"^\s*- name:\s*(\S+)\s*$", _ci_job_block("ci"), re.MULTILINE)
    assert host in matrix_names, (
        f"前端探针宿主分片 {host!r} 不在 matrix 里（现有: {matrix_names}）："
        "条件永远为假，4 条探针会静默不跑（死绿比慢更坏）"
    )
    assert host not in COST_GUARD_SHARDS, (
        f"前端探针宿主分片 {host!r} 是 cost 专项分片：会把无关步骤塞回计时关键路径，"
        "抵消本轮拆分收益"
    )


def _skip_to_line_end(text: str, i: int) -> int:
    """i 指向行注释的 `/`，返回行尾（换行符）下标。"""
    while i < len(text) and text[i] != "\n":
        i += 1
    return i


def _skip_block_comment(text: str, i: int) -> int:
    """i 指向块注释的 `/`，返回 `*/` 之后的下标。"""
    i += 2
    while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
        i += 1
    return i + 2


def _strip_jsonc_comments(text: str) -> str:
    """去掉 JSONC 的 // 与 /* */ 注释，只留有效配置（本文件含中文说明注释）。

    守卫要盯的是**配置本身**，不是注释里出现的字面量；不剥离会因注释里提到「全量 glob」
    而误报。配置字符串内不含 `//`（无 URL），故行注释按「到行尾」处理即安全。
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "/" and i + 1 < n and text[i + 1] == "/":
            i = _skip_to_line_end(text, i)
            continue
        if text[i] == "/" and i + 1 < n and text[i + 1] == "*":
            i = _skip_block_comment(text, i)
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def test_tsconfig_allowlist_is_not_a_full_glob() -> None:
    """tsconfig.json 的检查面 MUST 是显式 allowlist，MUST NOT 是全量 glob（防噪音灌闸）。"""
    effective = _strip_jsonc_comments(_read_guard_file(TSCONFIG))
    assert '"files"' in effective, (
        f'{TSCONFIG} 缺 "files" 显式 allowlist：无它时 tsc 会纳入全部 .js，'
        "把 199 条 DOM 噪音灌进 CI（永远红的噪音源）。"
    )
    for bad in ("**/*.js", "static/js/**", '"include"'):
        assert bad not in effective, (
            f"{TSCONFIG} 的有效配置出现全量检查面 {bad!r}：禁止把 allowlist 改成 glob —— "
            "实测全量 checkJs 有 219 条存量错误（199 条噪音），会变成永远红的门禁。"
        )
    assert "api-types.js" in effective, (
        f"{TSCONFIG} 的 allowlist 未含 api-types.js（API 边界类型的单一真相源）。"
    )
    assert "checkJs" in effective and "false" in effective, (
        f"{TSCONFIG} 未显式声明 checkJs 默认关闭（应仅由各文件首行 `// @ts-check` 逐个开启）。"
    )


def test_checked_api_modules_declare_ts_check() -> None:
    """allowlist 里的 JS 文件顶部 MUST 有 `// @ts-check`（否则 checkJs:false 下不被检查）。"""
    for path in (API_TYPES_JS, UPDATE_JS):
        head = _read_guard_file(path).splitlines()[:3]
        assert any(line.strip() == "// @ts-check" for line in head), (
            f"{path} 顶部缺 `// @ts-check`：checkJs 默认关闭时它不会被类型检查，"
            "allowlist 会变成空转。"
        )
    # 反向确认 allowlist 不是空转：api-types.js 真的承载了 typedef（否则检查面为空壳）。
    assert "@typedef" in _read_guard_file(API_TYPES_JS), (
        f"{API_TYPES_JS} 不含任何 @typedef：API 边界类型真相源为空壳，检查无意义。"
    )


# ── 发布链路超时护栏（Task 1，2026-10 韧性审计 P1）─────────────────────────────
# 背景：build-release.yml 的 5 个 job 全都没写 timeout-minutes，且 package_windows.py
# 里跑 PyInstaller 的 subprocess.run 没有 timeout ⇒ 一次卡住的 job（下载卡死 /
# PyInstaller 挂起）可以一路烧到 GitHub Actions 的 360 分钟（6 小时）硬上限，
# 白烧额度且无人发现。ci.yml 的 jobs.ci 已有 timeout-minutes（见上节），发布链路
# 却是个漏口径。
#
# 这里同样钉**上界**而不只"有没有"：`timeout-minutes: 3600` 的护栏比 Actions 默认
# 还宽，形同虚设，且从 YAML 上看不出意图。各 job 按实测构建时长留足余量。

BUILD_RELEASE_JOB_TIMEOUT_BOUNDS: dict[str, int] = {
    # build-windows 实测锚点：Windows Smoke job 全程 12:18（run 38209850232，2026-10-12；
    # 含 Install + pytest 9:02 + 构建段约 2–3 分钟 + 验包），30min 上界留足余量。
    "build-windows": 30,  # 实测构建段约 2–3min（见上注释），30min 上界留足余量
    "build-linux": 20,
    "build-macos": 20,
    "build-android": 30,  # Gradle 冷缓存下载 + APK 构建，波动最大
    "publish-github-release": 10,  # 只上传已构建好的产物，分钟级
}

# PyInstaller 子进程超时（秒）：20 分钟。取值 MUST 严格小于 build-windows job 的
# timeout-minutes × 60（子进程护栏要先到点，否则 job 被平台杀掉时人话错误来不及落盘）。
# 本次由 1800 → 1200 正是为修这个反转：原 1800s 与 job 级 30min 相同 ⇒ 真挂住时两级
# 护栏同时到点、job 级先杀全部进程，TimeoutExpired 的人话错误留不下来。实测构建段仅约
# 2–3 分钟（run 38209850232），1200s 仍远高于实测、且能稳定早于 job 级 30 分钟到点。
PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS = 1200


@pytest.mark.parametrize(
    ("job_name", "max_minutes"),
    list(BUILD_RELEASE_JOB_TIMEOUT_BOUNDS.items()),
)
def test_build_release_job_has_bounded_timeout(job_name: str, max_minutes: int) -> None:
    """build-release.yml 的每个 job 必须有 timeout-minutes，且值 MUST ≤ 各自上界。"""
    block = _job_block(BUILD_RELEASE_WORKFLOW, job_name)

    match = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", block, re.MULTILINE)
    assert match, (
        f"{BUILD_RELEASE_WORKFLOW} 的 jobs.{job_name} 没有 timeout-minutes：\n"
        "GitHub Actions 对单个 job 的默认上限是 360 分钟（6 小时），"
        "一次卡死的构建（下载卡死 / PyInstaller 挂起）会把 runner 烧满六小时才红——"
        "提交者早改去下一件事了。\n"
        f"修法：给 jobs.{job_name} 加 `timeout-minutes`（本守卫允许的上界是 {max_minutes}）。"
    )

    minutes = int(match.group(1))
    assert 0 < minutes <= max_minutes, (
        f"jobs.{job_name} 的 timeout-minutes = {minutes}，超过上界 {max_minutes}：\n"
        "写成 3600 之类的大值等于没设护栏（比 Actions 默认的 360 分钟还宽）。"
        "\n修法：按实测构建时长收紧；确需更长时先查清是哪一步变慢，而不是把闸门整体放开。"
    )


def test_pyinstaller_timeout_exits_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    """PyInstaller 子进程卡死（TimeoutExpired）时，打包 MUST 以 SystemExit(1) 退出。

    没有 timeout 的 subprocess.run 会永远挂起，直到 job 级 6 小时硬上限来收拾——
    比任何 timeout-minutes 都宽。加了 timeout 还必须接住 TimeoutExpired：不接的话
    异常会以裸 traceback 抛出，构建脚本"失败即 sys.exit(1)"的惯例被打破，且 stderr
    里留不下人话错误信息（卡死的 PyInstaller 只能从 traceback 反推）。
    """
    import package_windows

    # 清理阶段（rmtree build/ 与 dist/DeLector）不是本测试的对象：置为空转，避免每次
    # 跑测试都删掉开发者机器上的 PyInstaller 构建缓存，也避免把与超时无关的删除副作用
    # 混进断言。被测的是 PyInstaller 那一处 subprocess.run 的真实代码路径。
    monkeypatch.setattr(package_windows.shutil, "rmtree", lambda *args, **kwargs: None)

    # 捕获生产代码传给 subprocess.run 的真实 kwargs：此前只用自己的常量造 TimeoutExpired、
    # 不断言生产值 ⇒ 生产值被改成任何数测试都照绿（假绿口）。这里钉死生产 timeout 与本常量一致。
    captured_run_kwargs: dict[str, object] = {}

    def hang_forever(*args: object, **kwargs: object) -> None:
        captured_run_kwargs.update(kwargs)
        raise subprocess.TimeoutExpired(
            cmd=["python", "-m", "PyInstaller"], timeout=PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS
        )

    monkeypatch.setattr(package_windows.subprocess, "run", hang_forever)

    with pytest.raises(SystemExit) as exc:
        package_windows.build_windows()

    assert exc.value.code == 1, "PyInstaller 超时 MUST 以非零码退出（构建失败），而不是静默继续"

    assert captured_run_kwargs.get("timeout") == PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS, (
        f"生产代码传给 subprocess.run 的 timeout={captured_run_kwargs.get('timeout')!r}，"
        f"与 PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS={PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS} 不一致：\n"
        "子进程护栏的值必须与测试常量对齐，否则护栏形同虚设"
        "（假绿：生产值改成任何数测试都照绿）。"
    )


def test_pyinstaller_timeout_precedes_build_windows_job_guard() -> None:
    """子进程护栏 MUST 严格早于 build-windows 的 job 级护栏到点（设计不变量）。

    子进程 timeout 若 ≥ job 级 timeout-minutes，真挂住时两级护栏同时到点、job 级先杀全部
    进程，subprocess.TimeoutExpired 的人话错误来不及落盘 —— 提前反馈的意义荡然无存。分钟数
    从 BUILD_RELEASE_JOB_TIMEOUT_BOUNDS 取（护栏上界）换算成秒，严格大于子进程超时；不写死
    数字，随 bounds 调整自动跟随。
    """
    job_guard_seconds = BUILD_RELEASE_JOB_TIMEOUT_BOUNDS["build-windows"] * 60
    assert PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS < job_guard_seconds, (
        f"PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS={PYINSTALLER_SUBPROCESS_TIMEOUT_SECONDS}s 未严格小于 "
        f"build-windows job 级护栏 {BUILD_RELEASE_JOB_TIMEOUT_BOUNDS['build-windows']}min"
        f"（={job_guard_seconds}s）：\n"
        "子进程护栏若与 job 级护栏同时到点，job 被平台杀掉时 subprocess.TimeoutExpired 的"
        "人话错误来不及落盘。\n"
        "修法：把子进程超时降到严格小于 job 级 timeout-minutes × 60"
        "（实测构建段仅约 2–3 分钟，留足余量即可）。"
    )


# ── Windows 冒烟 job「测试先于构建」守卫（2026-10 windows smoke 自洽）──────────────
# 背景：windows-portable-smoke 此前只做「Install → Build → Verify(真启)」，**不跑 pytest**
# （安装步里装了 pytest 却从不调用，是死安装）⇒ 平台专属的测试失败只能等打 tag 后才暴露。
# 实证：v5.17.0 首次 tag 时四平台里 macOS 的一个测试红卡，导致 Publish GitHub Release
# 被跳过（tag 存在但无 Release）。修法：在 Build **之前**插入 `pytest -q` —— 测试红就
# 别再花约 3 分钟构建（实测构建段仅 2–3 分钟，run 38209850232；原「10 分钟」高估 3–5 倍）。
#
# 为什么钉「顺序」而不只钉「字符串在场」：把 pytest 步整段挪到 Build 之后，字符串依旧在场，
# 而「构建先跑完、测试失败照常发生」—— 提前反馈、省构建时间的意义荡然无存。故比**步骤
# 顺序**，与 test_frontend_route_contract_gate_precedes_pytest 同族。

PYTEST_RUN_NEEDLE = "pytest -q"
BUILD_STEP_NEEDLE = "Build Windows Portable"


def test_windows_smoke_runs_pytest_before_build() -> None:
    """windows-portable-smoke 的 pytest 步 MUST 早于 Build（测试红就别再构建）。

    定位到 **step 级**且用 `pytest -q` 作针脚：安装步里的 `pip install pyinstaller pytest`
    只是装工具（死安装），不算跑测试；只有以 `pytest -q` 为 run 命令的步才是真执行。
    """
    block = _job_block(CI_WORKFLOW, "windows-portable-smoke")
    steps = _steps_of(block)

    build_idx = next((i for i, s in enumerate(steps) if BUILD_STEP_NEEDLE in s), None)
    assert build_idx is not None, (
        f"{CI_WORKFLOW} 的 windows-portable-smoke 找不到 Build 步（{BUILD_STEP_NEEDLE!r}）："
        "冒烟 job 的构建步被改/被删？本守卫失去顺序锚点，请复核该 job 的结构。"
    )

    pytest_idx = next((i for i, s in enumerate(steps) if PYTEST_RUN_NEEDLE in s), None)
    assert pytest_idx is not None, (
        f"{CI_WORKFLOW} 的 windows-portable-smoke 没有执行 pytest 的步骤（{PYTEST_RUN_NEEDLE!r}）：\n"
        "该 job 此前只验「打包 + 真启」、不跑测试 —— 安装步里 `pip install pyinstaller pytest` "
        "装了 pytest 却从不调用（死安装）⇒ 平台专属的测试失败只能等打 tag 后才暴露"
        "（v5.17.0 首次 tag 的 macOS 红卡正是此形态，导致 Publish GitHub Release 被跳过、"
        "tag 存在但无 Release）。\n"
        "修法：在 Install dependencies 步之后、Build Windows Portable 步之前插入一步 "
        "`run: pytest -q` —— 测试红就别再花约 3 分钟构建"
        "（实测构建段仅 2–3 分钟，run 38209850232；原「10 分钟」高估 3–5 倍）。"
    )
    assert pytest_idx < build_idx, (
        f"{CI_WORKFLOW} 的 windows-portable-smoke 把 pytest 步排在了 Build **之后**：\n"
        "「测试先于构建」的顺序被破坏 —— 构建照跑、失败照常发生，提前反馈的意义荡然无存。\n"
        "修法：把 pytest 步挪回 Build Windows Portable 之前。"
    )
