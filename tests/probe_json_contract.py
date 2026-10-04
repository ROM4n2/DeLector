# -*- coding: utf-8 -*-
r"""`tools/*_probe.mjs` 的 `--json` 输出契约：标准形状 + 存量过渡清单（冻结轮）。

═══ 为什么是「冻结」而不是「全面统一」 ═══
`tools/` 下 27 个 `*_probe.mjs` 的 `--json` 输出**实跑**下来有 5 种形态（本文件所有
分类均来自逐个 `node tools/X.mjs --json` 的实测顶层键，**不是读源码推断**）：

  * 精确 `{failures, total, cases}` —— 4 个（标准）
  * 三键超集（额外带 `ok` / `samples`）—— 3 个
  * 用 `fail` 而非 `failures` —— 4 个
  * 扁平业务键（顶层键就是被测维度 / 场景自陈）—— 14 个
  * 其它（扁平且连 `ok` 都没有）—— 2 个

把它们全部统一成 `{failures, total, cases:[{name, ok}]}` 要动 23 个 probe + 约 13 个
wrapper，而且会把 `samples` / `requests` / `problems` 这些**丰富的结构化证据压成
`{name, ok}` 两个字段** ⇒ 诊断能力净损失。故本轮改为**冻结**：

  * 存量 23 个非标准探针登记进 `LEGACY_NONSTANDARD`（逐条带理由）；
  * **新增探针即标准**：不在清单里的探针 MUST 输出精确 `{failures, total, cases}`；
  * 清单**只减不增**（`LEGACY_BASELINE_COUNT` 钉死上限），否则"登记"会退化成永久豁免。

═══ 为什么常量放在这个 helper 而不放在 test_*.py 里 ═══
`tests/test_probe_wiring_guard.py` 的漏接线守卫把 `tests/**/test_*.py` 拼成 corpus
做子串匹配，判断某探针是否"被 wrapper 引用"。若把 23 个真实探针名写进某个
`test_*.py`，**光是提到名字就会让那 23 个探针被判成"已接线"** ⇒ 将来真 wrapper
被删掉，漏接线守卫照样绿。这与 `tests/probe_runner.py` 模块 docstring 里记下的
"文档即证据"哑雷是同一个坑（那边已用占位名规避）。

故本文件**刻意不叫 `test_*.py`**（同 `probe_runner.py` / `db_cleanup.py` 的既有做法，
pytest 不会收集它），把清单与跑探针的活儿都放这里：`test_probe_json_contract.py`
只 `import` 常量，名字不进 corpus。

═══ 判定口径：成功路径 ═══
`enc_coverage_degraded_probe` 与 `enc_known_lemmas_dedupe_probe` 有**两条输出路径**：
  * 早退路径（依赖数据缺失 / 环境不满足）输出 `{ok, error}`；
  * **成功路径**输出精确 `{failures, total, cases}`。
本契约**按成功路径判定**（实测二者成功路径均为三键 ⇒ 归入标准，不进过渡清单）。
早退路径的 `{ok, error}` 是"跑不起来"的自陈，不是契约的一种形态；它的存在由
wrapper 的退出码断言兜住，本清单不为它开口子。

同理 `wb_a1_bootstrap_probe` 必须带 `--fixture <path>` 才会输出 JSON（无参数时只
打印用法到 stderr 并退出 0）⇒ 本模块的 runner 对它自动补 fixture。
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"

# ── 标准契约 ────────────────────────────────────────────────────────────────
# 精确三键：多一个少一个都不算（超集/子集一律不合规）。
STANDARD_KEYS: frozenset[str] = frozenset({"failures", "total", "cases"})

# ── 存量过渡清单（只减不增） ────────────────────────────────────────────────
# 每条 MUST 带理由：没有理由的登记 = 无声的永久豁免。
LEGACY_NONSTANDARD: frozenset[str] = frozenset(
    {
        "cards_catalog_tag_probe",
        "cards_count_probe",
        "cards_wb_source_probe",
        "cards_workbench_no_review_probe",
        "enc_known_same_source_probe",
        "enc_open_race_probe",
        "enc_popover_clamp_probe",
        "ia_dom_mount_probe",
        "wb_a1_bootstrap_probe",
        "wb_cards_vocab_unwrap_probe",
        "wb_merge_probe",
        "wb_pair_persist_probe",
        "wb_pair_push_probe",
        "wb_phone_pull_probe",
        "wb_phone_pull_silent_probe",
        "wb_queue_probe",
        "wb_reader_rich_backfill_probe",
        "wb_rich_backfill_probe",
        "wb_rtc_connect_probe",
        "wb_rtc_reconnect_probe",
        "wb_search_probe",
        "wb_sync_probe",
        "wb_tags_probe",
    }
)

# 登记理由（键 MUST 与 LEGACY_NONSTANDARD 完全一致：不多不少）。
# 每条写清「实测形状 + 为什么暂不迁移」，不写理由的条目会被守卫判红。
LEGACY_REASONS: dict[str, str] = {
    # ── 三键超集（多了 ok / samples）──────────────────────────────────────
    "cards_catalog_tag_probe": (
        "超集 {ok, failures, total, cases, samples}：samples 是失败用例的结构化明细"
        "（比 cases[].ok 更能定位），压平会丢诊断信息"
    ),
    "cards_wb_source_probe": (
        "超集 {ok, failures, total, cases, samples}：同上，samples 承载来源判定证据"
    ),
    "cards_workbench_no_review_probe": (
        "超集 {ok, failures, total, cases, samples}：同上；本探针守 P0「白复习」回归，"
        "迁形状要同步改 wrapper，风险高于收益"
    ),
    # ── 用 fail 而非 failures ────────────────────────────────────────────
    "wb_a1_bootstrap_probe": (
        "{cases, fail, total}：计数键叫 fail 不是 failures；且必须带 --fixture 才有"
        "JSON 输出（无参数只打用法、退出 0），runner 已为它自动补 fixture"
    ),
    "wb_reader_rich_backfill_probe": "{cases, fail, total}：计数键叫 fail 不是 failures",
    "wb_rich_backfill_probe": "{cases, fail, total}：计数键叫 fail 不是 failures",
    "wb_search_probe": "{cases, fail, total}：计数键叫 fail 不是 failures",
    # ── 扁平业务键：顶层键即场景名（值是一句人话自陈）────────────────────
    "enc_known_same_source_probe": (
        "{ok, A, B, C, D, E}：扁平场景自陈，顶层键就是场景名，值为该场景的人话结论"
    ),
    "enc_open_race_probe": "{ok, A, A2, B, C, D}：扁平场景自陈（竞态时序各场景）",
    "enc_popover_clamp_probe": "{ok, 1, 2, 3, 4, 5}：扁平场景自陈（钳位各档位）",
    # ── 扁平业务键：顶层键即被测维度 ─────────────────────────────────────
    "cards_count_probe": "{ok, counts}：顶层是计数统计维度，不是 case 列表",
    "ia_dom_mount_probe": "{ok, dynamic, exam}：两个挂载维度各自自陈",
    "wb_cards_vocab_unwrap_probe": "{ok, unwrap}：单维度结论",
    "wb_phone_pull_probe": "{ok, gotPull, mergedCardIds, requests}：带 requests 请求流水",
    "wb_phone_pull_silent_probe": (
        "{ok, pullToastCount, explicitToastTotal, pullViewSwitches}：toast 计数维度"
    ),
    "wb_sync_probe": "{ok, put, requests}：带 requests 请求流水",
    "wb_tags_probe": "{ok, probes, problems}：probes 是探针自陈数组，problems 是问题清单",
    "wb_pair_persist_probe": (
        "{ok, persistedPair, restoredPairOnBoot, pushedWithNewKey, revokePosted, "
        "pairClearedAfterRevoke, requests}：配对持久化各维度 + 请求流水"
    ),
    "wb_pair_push_probe": (
        "{ok, putUrl, putHasPairKey, askedLocalKey, gotRemotePull, mergedCardIds, "
        "requests}：推送握手各环节证据 + 请求流水"
    ),
    "wb_rtc_connect_probe": (
        "{ok, channelCreated, offerHasPairKey, offerPostUrl, answerApplied, "
        "candidateApplied, connected, snapshotSentOnOpen, mergeSilent, mergedCardIds}"
        "：RTC 握手逐环节布尔/结构证据，压成 {name, ok} 会丢环节定位"
    ),
    "wb_rtc_reconnect_probe": (
        "{ok, pcCountAfterStart, pcCountAfterFailures, reconnectedAfterFailure, "
        "degradedAfterMaxFails, degradedWithoutWebRTC, httpFallbackAlive, "
        "noReconnectAfterDegrade}：重连/降级各维度证据"
    ),
    # ── 扁平且连 ok 都没有（裁决靠 problems/exit 码，不是 ok 字段）────────
    "wb_merge_probe": (
        "{aliasMigration, caseSensitivity, doubleImport, schemaMigration}："
        "连 ok 都没有的四维结论，改形状会动其 wrapper 的裁决口径"
    ),
    "wb_queue_probe": (
        "{slices, fixture, guards, idempotency, liveDailyNew, extraExempt, "
        "scopeNoTopUp, searchBypass, rebuildClearsExemptions, "
        "finishedStateScopeSwitch}：连 ok 都没有的十维结论"
    ),
}

# 冻结基线：本轮实跑得到的非标准探针数。清单长度 MUST NOT 超过它 ——
# 「新增探针即标准」的反面就是「存量不许变多」，否则冻结退化成豁免。
LEGACY_BASELINE_COUNT = 23

# 探针文件名约定：xxx_probe.mjs（与 test_probe_wiring_guard.py 的口径一致）
_PROBE_GLOB = "*_probe.mjs"

# 需要额外实参才能产出 JSON 的探针（键=探针名，值=要补的 argv 片段工厂名）
_NEEDS_FIXTURE: frozenset[str] = frozenset({"wb_a1_bootstrap_probe"})

_FIXTURE_CACHE: dict[str, str] = {}


def probe_names() -> list[str]:
    """`tools/` 下全部探针名（不含 `.mjs`），按名字排序。"""
    return sorted(p.name[: -len(".mjs")] for p in TOOLS_DIR.glob(_PROBE_GLOB))


def a1_fixture_path() -> Path:
    """用仓库**真实数据源**生成 `wb_a1_bootstrap_probe` 的 fixture（进程内缓存一次）。

    与 `tests/test_german_workbench.py::_a1_bootstrap_fixture` 同源同口径：
      rows   ← `delector.core.database.get_vocab_by_cefr("A1", scope="all")["words"]`
      inline ← `delector.data.a1_workbench_dict.A1_WORKBENCH_SEED / _CUSTOM`
    刻意**不**改用合成小 fixture：探针场景 1 是"服务端 704 行 vs 内联 682+22 逐字段
    等价"，行数不足会让探针真的判失败（exit≠0），把契约守卫污染成行为断言。
    """
    cached = _FIXTURE_CACHE.get("a1")
    if cached is not None:
        return Path(cached)

    from delector.core.database import get_vocab_by_cefr
    from delector.data.a1_workbench_dict import (
        A1_WORKBENCH_CUSTOM,
        A1_WORKBENCH_SEED,
    )

    payload = {
        "rows": get_vocab_by_cefr("A1", scope="all")["words"],
        "inline": {"seed": A1_WORKBENCH_SEED, "custom": A1_WORKBENCH_CUSTOM},
    }
    dest = Path(tempfile.gettempdir()) / f"delector_a1_bootstrap_fixture_{os.getpid()}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _FIXTURE_CACHE["a1"] = str(dest)
    return dest


def run_probe_json(probe_name: str) -> dict[str, Any]:
    """跑 `node tools/<name>.mjs --json`（必要时补 `--fixture`）并返回解析后的输出。

    判的是**实跑输出**，不是源码文本：改注释 / 改源码里的字样都不会影响这里的判定，
    只有真正改掉 stdout 上的 JSON 顶层键才会红。
    """
    probe = TOOLS_DIR / f"{probe_name}.mjs"
    assert probe.exists(), f"缺少 tools/{probe_name}.mjs（文件缺失，无法判定契约）"

    argv = ["node", str(probe), "--json"]
    if probe_name in _NEEDS_FIXTURE:
        argv += ["--fixture", str(a1_fixture_path())]

    res = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO_ROOT),
    )
    assert res.returncode == 0, (
        f"探针 {probe_name} 退出码 {res.returncode}（契约判定要求成功路径）：\n"
        f"stdout(前 500 字):\n{res.stdout[:500]}\nstderr(前 500 字):\n{res.stderr[:500]}"
    )
    try:
        out: Any = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"探针 {probe_name} 的 --json 输出不是合法 JSON：{exc}\n"
            f"stdout(前 500 字):\n{res.stdout[:500]}\nstderr(前 500 字):\n{res.stderr[:500]}"
        ) from exc
    assert isinstance(out, dict), (
        f"探针 {probe_name} 的 --json 顶层不是对象：{type(out)!r}"
    )
    return out
