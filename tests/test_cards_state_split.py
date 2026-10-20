# -*- coding: utf-8 -*-
"""cd-state.js 状态容器验收（计划 2026-10-20-cards-state-container Task 2）。

被测对象 `static/js/cd-state.js`：`cards.js` 的 15 个模块级可变状态收口成的单一容器。
本文件只断言**结构、初值与访问器行为**；规则面的禁令（DOM/网络/提示/定时器/越界 import）
由 `tools/check_frontend_layers.py` 的 `LAYER_SPEC["cd-state.js"]` 承担，此处不重复造一条。

1. test_cd_state_shape_and_initial_values
   五簇齐全，24 个叶子字段逐一等于 `cards.js` 原文初值（逐条注释标出源行）。
   注意 `prep.loading` 是「正在飞的那次请求」而不是布尔 —— 初值 `null`、不是 `false`。
2. test_enter_segment_writes_exactly_three_fields
   `enterSegment` 逐字复刻 `setCardSegment` 的三写（segment / index / flipped），
   其余字段一个都不许动。**必须先把容器写脏再切段**：初值是 0/false 时
   「漏写一个复位」在纯前后 diff 里是隐形的。
3. test_step_deck_state_does_not_clamp
   `stepDeck` 今天**没有任何夹取**，边界靠按钮 `disabled` 挡 + `renderDeckStage`
   渲染期纠正（`if (deckIndex >= deck.length) deckIndex = Math.max(0, ...)`）。
   这条用例是「顺手加固」的哨兵：任何 clamp 实现都会在这里红。
4. test_step_deck_state_resets_flip
   移动卡位必须复位翻面（`stepDeck` 的第二写）。
5. test_cd_state_declares_no_top_level_mutable
   token 级：顶层 `let`/`var` == 0、import == 0（L1 纯层，`allowed_imports=()`）。

**执行方式**：`cd-state.js` 不 import 任何模块 ⇒ 它是本仓少数能被 node **真跑**的模块
（`cards.js` 不行：`player.js:77` 在模块求值期就碰 `localStorage`）。故行为断言全部走
node ESM 探针而不是正则读源码 —— 正则看不出夹取，也看不出「只写了两个字段」。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.check_frontend_layers import (  # noqa: E402
    import_targets,
    read_js,
    top_level_mutable_tokens,
)

CD_STATE_REL = "static/js/cd-state.js"

CLUSTERS = ("catalog", "deck", "quiz", "prep", "toast")

#: `cards.js` 的 15 个模块级 `let` 展开成容器后的 24 个叶子字段。
#: 15 → 24 是因为 5 个 `let` 持有对象（`cachedCards` / `cachedDueCards` / `quizState`
#: 拆成多个字段）。逐条硬编码并标出源行，禁止「看起来合理」的重写 ——
#: 设计稿 §6.1 记录过初稿把 `segment` 写成 `'vocab'`、`viewMode` 写成 `'grid'`
#: （实际是 `"due"` / `"deck"`），那会静默改变首屏。
EXPECTED_INITIAL: Dict[Tuple[str, ...], Any] = {
    # ── 簇 1 卡册浏览 ──
    ("catalog", "segment"): "due",  # cards.js:29  let cardSegment = "due"
    ("catalog", "viewMode"): "deck",  # cards.js:30  let cardViewMode = "deck"
    ("catalog", "cards", "vocab_cards"): [],  # cards.js:33  cachedCards.vocab_cards
    ("catalog", "cards", "grammar_cards"): [],  # cards.js:33  cachedCards.grammar_cards
    ("catalog", "dueCards", "due_vocab"): [],  # cards.js:34  cachedDueCards.due_vocab
    ("catalog", "dueCards", "due_grammar"): [],  # cards.js:34  cachedDueCards.due_grammar
    ("catalog", "dueCards", "due_count"): 0,  # cards.js:34  cachedDueCards.due_count
    # ── 簇 2 翻牌卡组 ──
    ("deck", "index"): 0,  # cards.js:31  let deckIndex = 0
    ("deck", "flipped"): False,  # cards.js:32  let deckFlipped = false
    ("deck", "lastFlipTime"): 0,  # cards.js:36  let _lastFlipTime = 0
    ("deck", "reviewInFlight"): False,  # cards.js:429 let _reviewInFlight = false
    # ── 簇 3 测验（cards.js:659-667 的 quizState，单个就地可变对象）──
    ("quiz", "mode"): "flashcard",  # cards.js:660
    ("quiz", "queue"): [],  # cards.js:661
    ("quiz", "index"): 0,  # cards.js:662
    ("quiz", "correct"): 0,  # cards.js:663
    ("quiz", "wrong"): 0,  # cards.js:664
    ("quiz", "isFlipped"): False,  # cards.js:665
    ("quiz", "allVocab"): [],  # cards.js:666
    # ── 簇 4 介词矩阵（cards.js:1102-1106）──
    ("prep", "cache"): None,  # cards.js:1102 _prepMatrixCache = null
    ("prep", "loading"): None,  # cards.js:1103 _prepLoading = null（正在飞的请求，非布尔）
    ("prep", "caseFilter"): "",  # cards.js:1104 _prepCaseFilter = ""
    ("prep", "searchQuery"): "",  # cards.js:1105 _prepSearchQuery = ""
    ("prep", "searchTimer"): None,  # cards.js:1106 _prepSearchTimer = null
    # ── 簇 5 瞬时 UI ──
    ("toast", "undoTimer"): None,  # cards.js:35  let undoToastTimer = null
}

#: 探针公共前置：`snap()` 深拷贝容器（避免 before/after 指向同一对象）。
_PROBE_PRELUDE = """
const snap = () => JSON.parse(JSON.stringify(cardState));
const out = {};
"""


def _probe(tmp_path: Path, body: str) -> Dict[str, Any]:
    """把 cd-state.js 原文复制成 `.mjs` 到临时目录，在 node 里真跑 body，回传 `out`。

    为什么复制而不是直接 import 原文件：扩展名是 `.js` 且 `static/js/` 下没有
    `package.json` 的 `"type": "module"` ⇒ node 会按 CJS 解析该文件，`export` 直接
    SyntaxError。它不 import 任何模块，所以「复制原文」不改变任何被测语义。
    """
    src = REPO_ROOT / CD_STATE_REL
    assert src.exists(), f"{CD_STATE_REL} must exist"
    (tmp_path / "cd-state.mjs").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    driver = tmp_path / "probe.mjs"
    driver.write_text(
        "import { cardState, enterSegment, stepDeckState } from './cd-state.mjs';\n"
        + _PROBE_PRELUDE
        + body
        + "\nprocess.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, f"node probe failed on {CD_STATE_REL}:\n{proc.stderr}"
    return cast(Dict[str, Any], json.loads(proc.stdout))


def _flatten(value: Any, prefix: Tuple[str, ...] = ()) -> Dict[Tuple[str, ...], Any]:
    """把嵌套容器摊平成「路径 → 叶子值」。空容器本身当叶子（否则空簇会隐形）。"""
    if isinstance(value, dict):
        if not value:
            return {prefix: value}
        flat: Dict[Tuple[str, ...], Any] = {}
        for key, sub in value.items():
            flat.update(_flatten(sub, prefix + (key,)))
        return flat
    return {prefix: value}


def _fingerprint(value: Any) -> str:
    """类型敏感指纹：Python 里 `False == 0`，初值写错（false→0）必须红，不能靠 `==`。"""
    return f"{type(value).__name__}:{value!r}"


def _changed_paths(
    before: Dict[str, Any], after: Dict[str, Any]
) -> List[Tuple[str, ...]]:
    left = {path: _fingerprint(v) for path, v in _flatten(before).items()}
    right = {path: _fingerprint(v) for path, v in _flatten(after).items()}
    return sorted(path for path in set(left) | set(right) if left.get(path) != right.get(path))


# ══ 1. 形状与初值 ════════════════════════════════════════════════════════════


def test_cd_state_shape_and_initial_values(tmp_path: Path) -> None:
    """五簇齐全，且 24 个叶子字段逐一等于 cards.js 原文初值（类型敏感）。"""
    state = _probe(tmp_path, "out.state = snap();\n")["state"]

    assert sorted(state) == sorted(CLUSTERS), (
        "cardState 必须恰好有五个簇 "
        f"{sorted(CLUSTERS)}，实际: {sorted(state)}"
    )

    actual = {path: _fingerprint(v) for path, v in _flatten(state).items()}
    expected = {path: _fingerprint(v) for path, v in EXPECTED_INITIAL.items()}

    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    wrong = sorted(
        path for path in expected.keys() & actual.keys() if actual[path] != expected[path]
    )
    assert not (missing or extra or wrong), (
        "cd-state.js 初值漂移（每条 MUST 逐字等于 cards.js 原文）\n"
        f"  缺失字段: {missing}\n"
        f"  多余字段: {extra}\n"
        f"  值/类型不符: {[(path, expected[path], actual[path]) for path in wrong]}"
    )

    # 15 个模块级 let 展开成 24 个叶子：数字写进断言里，避免「少搬一个状态」被静默放过。
    assert len(EXPECTED_INITIAL) == 24, "期望表本身被改动（原文件是 15 个 let / 24 个叶子字段）"


# ══ 2. enterSegment：三写不变量 ══════════════════════════════════════════════

_DIRTY_BODY = """
cardState.catalog.viewMode = 'grid';
cardState.catalog.cards.vocab_cards.push({ id: 'dirty' });
cardState.catalog.dueCards.due_count = 42;
cardState.deck.index = 7;
cardState.deck.flipped = true;
cardState.deck.lastFlipTime = 1234;
cardState.deck.reviewInFlight = true;
cardState.quiz.index = 3;
cardState.quiz.isFlipped = true;
cardState.prep.cache = { groups: ['dirty'] };
cardState.prep.caseFilter = 'Dat';
cardState.prep.searchTimer = 7;
cardState.toast.undoTimer = 9;
"""


def test_enter_segment_writes_exactly_three_fields(tmp_path: Path) -> None:
    """`enterSegment('prep')` 只允许写 catalog.segment / deck.index / deck.flipped 三处。

    先写脏整个容器：初值全为 0/false 时，「漏写 deck.flipped = false」在前后 diff 中
    完全隐形（false → false），该不变量就等于没人守。
    """
    out = _probe(
        tmp_path,
        _DIRTY_BODY + "out.before = snap();\nenterSegment('prep');\nout.after = snap();\n",
    )
    after = out["after"]

    assert after["catalog"]["segment"] == "prep", "enterSegment 必须写 catalog.segment"
    assert after["deck"]["index"] == 0, "enterSegment 必须把 deck.index 复位为 0"
    assert after["deck"]["flipped"] is False, "enterSegment 必须把 deck.flipped 复位为 false"

    changed = _changed_paths(out["before"], after)
    assert changed == [
        ("catalog", "segment"),
        ("deck", "flipped"),
        ("deck", "index"),
    ], f"enterSegment 只许写这三处，实际改动: {changed}"


# ══ 3. stepDeckState：不得夹取 ═══════════════════════════════════════════════


def test_step_deck_state_does_not_clamp(tmp_path: Path) -> None:
    """越界必须如实越界：`stepDeck` 无夹取，夹取在 `renderDeckStage` 渲染期。

    这条是「顺手加固」的哨兵（设计稿 §6.1 警告块：初稿的 `advanceDeck(delta, total)`
    自带 `Math.max/ Math.min`，是**行为变更**）。加了 clamp 的实现在这里必红。
    """
    out = _probe(
        tmp_path,
        "out.before = snap();\n"
        "stepDeckState(-1);\n"
        "out.afterNegative = snap();\n"
        "cardState.deck.index = 99;\n"
        "stepDeckState(1);\n"
        "out.afterPositive = snap();\n",
    )

    assert out["before"]["deck"]["index"] == 0
    assert out["afterNegative"]["deck"]["index"] == -1, (
        "stepDeckState(-1) 从 0 出发必须得到 -1（夹取到 0 是行为变更，不是加固）："
        f"实际 {out['afterNegative']['deck']['index']!r}"
    )
    assert out["afterPositive"]["deck"]["index"] == 100, (
        "stepDeckState(+1) 从 99 出发必须得到 100（夹取到 99 是行为变更）："
        f"实际 {out['afterPositive']['deck']['index']!r}"
    )


# ══ 4. stepDeckState：复位翻面 ═══════════════════════════════════════════════


def test_step_deck_state_resets_flip(tmp_path: Path) -> None:
    """移动卡位必须复位翻面（`stepDeck` 的第二写），且位移如实等于 delta。"""
    out = _probe(
        tmp_path,
        "cardState.deck.flipped = true;\n"
        "cardState.deck.index = 4;\n"
        "stepDeckState(2);\n"
        "out.after = snap();\n",
    )
    after = out["after"]

    assert after["deck"]["flipped"] is False, "stepDeckState 必须把 deck.flipped 置 false"
    assert after["deck"]["index"] == 6, f"deck.index 应 4+2=6，实际 {after['deck']['index']!r}"


# ══ 5. L1 纯层：零顶层可变状态、零 import ═══════════════════════════════════


def test_cd_state_declares_no_top_level_mutable() -> None:
    """顶层（花括号净深度 0）`let`/`var` 计数必须为 0，且不 import 任何模块。

    状态只许活在 `cardState` 这一个 `const` 里；一旦有人在文件顶层重新长出 `let`，
    「写入面是一份清单」这个前提就没了。禁令本身由分层闸执行，此处是同一判据的
    就近钉子（闸被误改时这里仍会红）。
    """
    path = REPO_ROOT / CD_STATE_REL
    assert path.exists(), f"{CD_STATE_REL} must exist"
    _raw, toks = read_js(path)

    mutable = [f"{t.text} (line {t.line})" for t in top_level_mutable_tokens(toks)]
    assert mutable == [], f"{CD_STATE_REL} 顶层可变状态必须为 0，实际: {mutable}"

    targets = [spec for _lineno, spec, _form in import_targets(toks)]
    assert targets == [], f"{CD_STATE_REL} 是 L1 纯层（allowed_imports=()），不许 import: {targets}"
