# -*- coding: utf-8 -*-
"""Task 5 前端行为探针驱动（红线 11）：node 直跑 tests/test_hard_sentences_probe.mjs。

探针用 node:vm 的 SourceTextModule 把 static/js/hard-sentences.js **真源码**逐字节
加载进沙箱，由自定义 linker 桩掉 ./core.js（api/esc/notify）唯一依赖，从模块命名
空间驱动真实控制器（enterHardSentences / revealTree / lookupWord / addCard /
nextCard / stopHardSentences / setHardSource / pickHardMaterial / setHardLevel），
把四条前后端契约逐字段钉死（对照 delector/routes/syntax_hard.py 与规格 §3）：

  1. GET  /api/syntax/hard-sentences
     → {items:[{sentence, score, level, dimensions, path, source,
                source_id, sentence_index}]}
     （source_id int、source 枚举、dimensions 子键
      clause_depth/clause_count/passive/subjunctive/verb_last/relative_clause/length
      各含 value/score）
  2. GET  /api/syntax/hard-sentences/detail → analysis:{clause_tree, topology}
  3. POST /api/syntax/hard-sentence/trials body 七字段
     {source, source_id, sentence_index, level, score, revealed, duration_sec}
     → {trial_id}
  4. POST /api/cards/grammar 字段拼装（照 GrammarCardReq：
     article_id/sentence_context/grammar_name/cefr_level/explanation_zh/
     rule_formula/corrected_form/error_type）

并内置 3 个变异用例（dimensions clause_depth→clause_dep / detail 删 topology /
榜单 item 缺 path）证明探针非恒真：契约字段名改错重跑同一场景，探针必须红，否则
探针自身退出码 1。

运行（仓库根）：$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_hard_sentences_probe.py -v
node 缺失时整文件显式 skip（显式理由），既不让 CI 因缺 node 变红，也不静默假绿。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tests" / "test_hard_sentences_probe.mjs"

pytestmark = pytest.mark.skipif(
    not shutil.which("node"),
    reason="node 不在 PATH 上：前端行为探针需要 node 直跑真源码 hard-sentences.js",
)


def _run_probe():
    """node --experimental-vm-modules 直跑探针（vm.SourceTextModule 需要该 flag）。"""
    res = subprocess.run(
        ["node", "--experimental-vm-modules", "--no-warnings", str(PROBE), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return res


def test_hard_sentences_probe_contract_pinned():
    """四条契约域 + 行为路径全绿，断言数不被掏空（防探针恒真化）。"""
    res = _run_probe()
    assert res.returncode == 0, (
        "hard-sentences 行为探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out.get("ok") is True
    # 四条契约域必须显式 pass（hard_list / data_contract / detail_analysis /
    # trials_persist / cards_grammar）
    for name in (
        "hard_list",
        "data_contract",
        "detail_analysis",
        "trials_persist",
        "cards_grammar",
    ):
        assert out["contracts"].get(name) == "pass", f"契约域 {name} 未通过：{out['contracts']}"
    # 行为路径域（查词/选源/成绩汇总）也必须 pass
    for name in ("lookup", "source_switch", "summary"):
        assert out["contracts"].get(name) == "pass", f"行为路径域 {name} 未通过：{out['contracts']}"
    # 断言数下限：探针被悄悄砍断言（恒真化）时这里红
    assert out["probeChecks"] >= 25, f"探针断言数过低（{out['probeChecks']}），疑被掏空恒真化"


def test_hard_sentences_probe_mutations_caught():
    """变异验证（红线 11）：契约字段名改错/删掉，探针必须捕获（红），证明非恒真。"""
    res = _run_probe()
    assert res.returncode == 0, (
        "hard-sentences 行为探针失败：\nstdout:\n%s\nstderr:\n%s" % (res.stdout, res.stderr)
    )
    out = json.loads(res.stdout)
    assert out["mutations"], "探针没有内置任何变异用例（恒真风险）"
    for m in out["mutations"]:
        assert m["caught"] is True, (
            f"变异 {m['name']} 未被探针捕获 → 探针恒真（死测）：{m.get('sample')}"
        )