# -*- coding: utf-8 -*-
"""卡面「工作台来源」行为探针接线（ADR-0016 审计 P0 Task 5）。

说谎事故：统一池把工作台背过的词投影进 vocab_cards，但投影侧（core/vocab_pool.py）
只写 fsrs_s / fsrs_d / fsrs_lapses，**不写** due_date / correct_count / wrong_count
⇒ cards.js 正面页脚原会显示「⏳ 待复习 · 0 正 / 0 误」，而用户在背词工作台背了 5 次。
「N 正 / N 误」是**卡盒 DSR 侧**统计，对工作台词恒为 0 —— 纯字符串存在式断言证明不了
「真渲染出来的那行文案到底长什么样」，必须真跑（项目红线 11）。

tools/cards_wb_source_probe.mjs 按括号配对把 static/js/cards.js 里真实的
cardStatsTag + renderDeckStage 整段切出来丢进 node:vm 沙箱真跑，本文件只桩
document / esc / jsAttr，读回 renderDeckStage 写进容器的真 innerHTML 再断言文案。

本用例只负责：跑探针 `--json` → 断言 `failures == 0` 且场景数 ≥ 8。写法对齐
tests/test_enc_i1_probe.py（含 subprocess 调用与 UTF-8 编码处理）。
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROBE = ROOT / "tools" / "cards_wb_source_probe.mjs"


def _run_probe():
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
        return json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            "探针 --json 输出不是合法 JSON：%s\nstdout(前 500 字):\n%s\nstderr(前 500 字):\n%s"
            % (exc, res.stdout[:500], res.stderr[:500])
        )


def test_cards_wb_source_probe_reports_no_failures():
    """动态探针：真渲染卡面，钉死「工作台词说工作台的实话 / 非工作台词逐字不变」。"""
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    assert PROBE.exists(), "缺少 tools/cards_wb_source_probe.mjs 动态探针"
    out = _run_probe()

    assert out["failures"] == 0, "探针有失败场景：%r" % (
        [c for c in out["cases"] if not c["ok"]],
    )
    assert out["total"] >= 8, "探针场景数异常偏少（%d），可能场景被删" % out["total"]

    names = [c["name"] for c in out["cases"]]
    # 关键场景存在性钉死：日后删掉关键场景也必红，不允许「删场景换全绿」。
    for needle in ("工作台词", "逐字不变", "字符串数值", "脏值", "不暗示"):
        assert any(needle in n for n in names), (
            "探针缺少关键场景「%s」，场景集合：%r" % (needle, names)
        )


def test_cards_wb_source_probe_samples_match_backend_predicate():
    """探针样例必须与后端 /api/cards/due 的 `COALESCE(fsrs_s, 0) > 0` 同口径。

    前端判据（MUST NOT 与 main.py:1758 的 SQL 谓词分叉）若改成 `IS NOT NULL`
    之类的更宽口径，自建未评级词（fsrs_s 为 NULL）会被误判成「来自工作台」，
    于是普通 reader 卡的页脚不再显示真实的 DSR 正/误统计。口径一致性由
    tests/test_server.py 端到端保证；本用例只钉住探针喂进去的两个样本形状
    与真渲染结果（null ⇒ 旧文案；>0 ⇒ 工作台文案）。
    """
    if not shutil.which("node"):
        pytest.skip("node 不在 PATH 上，跳过动态探针")
    out = _run_probe()

    reader = out["samples"]["readerUnchanged"]
    assert "工作台" not in reader, (
        "fsrs_s=null 的普通 reader 卡被误判成工作台来源（与 due 队列 SQL 口径分叉）：%r" % reader
    )
    assert "正" in reader and "误" in reader, (
        "非工作台词的卡面必须照旧显示卡盒 DSR 的正/误统计：%r" % reader
    )

    wb = out["samples"]["workbench"]
    assert "工作台" in wb, "fsrs_s>0 的工作台词卡面未显示工作台来源：%r" % wb
    assert "正" not in wb and "误" not in wb, (
        "工作台词卡面不得显示卡盒 DSR 的正/误统计（对工作台词恒为 0 = 说谎）：%r" % wb
    )
