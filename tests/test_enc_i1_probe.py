# -*- coding: utf-8 -*-
"""遇见区 i+1 就近选材纯函数行为探针接线（Task 4 · Phase B）。

static/js/enc-i1.js 是零依赖纯逻辑 ES module；tools/wb_enc_i1_probe.mjs 用 node:vm
切**真实源码**（去 `export` 后注入沙箱）真跑，钉死「覆盖率分母 / 区间边界 / 排序 /
纯度 / 推荐」这些跨边界契约（项目红线 11：字符串存在式断言是死测）。

本用例只负责：跑探针 `--json` → 断言 `failures == 0` 且场景数 ≥ 6。写法对齐
`tests/test_german_workbench.py::test_rich_backfill_probe_reports_no_failures`（含
subprocess 调用与 UTF-8 编码处理）。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tools" / "wb_enc_i1_probe.mjs"


def test_enc_i1_probe_reports_no_failures():
    """动态探针：把真实 static/js/enc-i1.js 抽出来在 node:vm 里真跑。

    静态断言证明不了「0.85 边界真的落在 i1」「分母真的用 totalTokens 而非
    lemma_seq.length」「排序真的不改入参」—— 这些是行为，只有真跑才知道。
    tools/wb_enc_i1_probe.mjs 只提供桩 knownSet，用 node:vm 真跑 enc-i1.js 真实源码，
    覆盖：区间边界、排序（分组 / rate 降序 / 同分 id 升序 / available=false 排最后）、
    topPick、纯度（不改入参）、hasCoverage、分母语义、available 判据；并输出 JSON 供
    本用例断言。
    """
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    assert PROBE.exists(), "缺少 tools/wb_enc_i1_probe.mjs 动态探针"
    res = subprocess.run(
        ["node", str(PROBE), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    assert res.returncode == 0, "探针执行失败：\n%s\n%s" % (res.stdout, res.stderr)
    try:
        out = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "探针 --json 输出不是合法 JSON：%s\nstdout(前 500 字):\n%s\nstderr(前 500 字):\n%s"
            % (exc, res.stdout[:500], res.stderr[:500])
        )

    assert out["failures"] == 0, "探针有失败场景：%r" % (
        [c for c in out["cases"] if not c["ok"]],
    )
    assert out["total"] >= 6, "探针场景数异常偏少（%d），可能场景被删" % out["total"]

    names = [c["name"] for c in out["cases"]]
    # 关键场景存在性钉死：日后删掉关键场景也必红，不允许「删场景换全绿」。
    for needle in ("区间边界", "排序", "topPick", "纯度", "分母", "hasCoverage"):
        assert any(needle in n for n in names), (
            "探针缺少关键场景「%s」，场景集合：%r" % (needle, names)
        )
