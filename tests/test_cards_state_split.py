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
   「漏写一个复位」在纯前后 diff 里是隐形的。写脏走 `__dirtyAll()` 递归遍历
   **全部 24 个叶子**并逐个注入哨兵 —— 手列清单漏掉的那 11 个叶子，其「被写回
   初值」与初始状态无差别，同样是隐形的。
3. test_step_deck_state_changes_exactly_two_fields
   `stepDeckState` 与 `enterSegment` 同等待遇：改动路径集合 MUST 恰好是
   {deck.index, deck.flipped}。少了这条，给 `stepDeck` 顺手加第三个写
   （例如 `deck.lastFlipTime`）在其余全部用例里都是绿的。
4. test_step_deck_state_does_not_clamp
   `stepDeck` 今天**没有任何夹取**，边界靠按钮 `disabled` 挡 + `renderDeckStage`
   渲染期纠正（`if (deckIndex >= deck.length) deckIndex = Math.max(0, ...)`）。
   这条用例是「顺手加固」的哨兵：任何 clamp 实现都会在这里红。
5. test_step_deck_state_resets_flip
   移动卡位必须复位翻面（`stepDeck` 的第二写）。
6. test_cd_state_declares_no_top_level_mutable
   token 级：顶层 `let`/`var` == 0、import == 0（L1 纯层，`allowed_imports=()`）。
7. 六条**变异自证**（`test_mutation_*`，计划 Task 6）
   前面几个任务各自手工做过一次「拆掉机制 ⇒ 用例变红」的验证；这里把它们固化成常驻
   用例 —— 否则「不变量确实有人守」这件事只活在某次会话的记录里，下一个人删掉
   `deck.flipped` 复位时，§2 的断言是否真的会红，只能靠再猜一次。
   纪律：每条断言**期望的规则名/断言文本**，不接受「exit 非 0」；每条只碰 tmp 副本，
   真实树一个字节都不许动（`_gate_with_mutation` 每次调用都逐字节对账）。
   M1 cards.js 顶层 `let` ⇒ 闸报 `零顶层可变状态契约禁mutable-state`（点名注入行）
   M2 cd-state.js 的 `document.` ⇒ 闸报 `L1 纯状态容器禁dom`
   M3 cd-state.js 的 `import { esc } from './core.js'` ⇒ 闸报 `L1 纯状态容器越界import(core.js)`
   M4 删掉 `enterSegment` 的 `deck.flipped = false` ⇒ §2 用例红且点名该字段
   M5 给 `stepDeckState` 加 `Math.max(0, …)` 夹取 ⇒ §4 用例红且点名「夹取是行为变更」
   M6 探针丢掉 cd-state.js 接缝 ⇒ 具名 exit 1（含容器名），不是裸 ReferenceError

**执行方式**：`cd-state.js` 不 import 任何模块 ⇒ 它是本仓少数能被 node **真跑**的模块
（`cards.js` 不行：`player.js:77` 在模块求值期就碰 `localStorage`）。故行为断言全部走
node ESM 探针而不是正则读源码 —— 正则看不出夹取，也看不出「只写了两个字段」。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple, cast

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.check_frontend_layers import (  # noqa: E402
    collect_violations,
    import_targets,
    read_js,
    top_level_mutable_tokens,
)

CD_STATE_REL = "static/js/cd-state.js"
JS_DIR_REL = "static/js"

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
let __dirtySeq = 0;
const __dirtyPaths = [];
function __dirtyAll(node, path) {
  for (const key of Object.keys(node)) {
    const here = path ? path + '.' + key : key;
    const value = node[key];
    if (Array.isArray(value)) {
      // 数组按叶子处理：塞一个哨兵元素，写回 [] 才看得出差别。
      __dirtySeq += 1;
      __dirtyPaths.push(here);
      value.push({ __dirty__: here, seq: __dirtySeq });
    } else if (value !== null && typeof value === 'object') {
      __dirtyAll(value, here);
    } else {
      // 标量叶子：布尔取反，数字/字符串/初值 null 一律换成路径可辨认的哨兵，
      // 保证「写回初值」必然表现为一个 changed path。
      __dirtySeq += 1;
      __dirtyPaths.push(here);
      if (typeof value === 'boolean') node[key] = !value;
      else if (typeof value === 'number') node[key] = 900000 + __dirtySeq;
      else if (typeof value === 'string') node[key] = '__dirty__:' + here + '#' + __dirtySeq;
      else if (value === null) node[key] = '__dirty__:' + here + '#' + __dirtySeq;
      else throw new Error('unhandled leaf at ' + here + ': ' + typeof value);
    }
  }
}
"""


def _cd_state_source() -> str:
    """真实 `cd-state.js` 的原文（按字节解码，不经过换行转换）。"""
    path = REPO_ROOT / CD_STATE_REL
    assert path.exists(), f"{CD_STATE_REL} must exist"
    return path.read_bytes().decode("utf-8")


def _probe_source(
    tmp_path: Path, source: str, body: str, label: str = CD_STATE_REL
) -> Dict[str, Any]:
    """把给定源码写成 `.mjs` 到临时目录，在 node 里真跑 body，回传 `out`。

    为什么复制而不是直接 import 原文件：扩展名是 `.js` 且 `static/js/` 下没有
    `package.json` 的 `"type": "module"` ⇒ node 会按 CJS 解析该文件，`export` 直接
    SyntaxError。它不 import 任何模块，所以「复制原文」不改变任何被测语义 ——
    §7 的变异用例正是靠这一点，把**同一份断言**指向带变异的副本。
    """
    (tmp_path / "cd-state.mjs").write_bytes(source.encode("utf-8"))

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
    assert proc.returncode == 0, f"node probe failed on {label}:\n{proc.stderr}"
    return cast(Dict[str, Any], json.loads(proc.stdout))


def _probe(tmp_path: Path, body: str) -> Dict[str, Any]:
    """真实 `cd-state.js` 上的探针（§1-§5 行为用例的统一入口）。"""
    return _probe_source(tmp_path, _cd_state_source(), body)


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

#: 探针里「把容器写脏」的统一前置：`__dirtyAll()` 递归遍历**全部叶子**并注入哨兵。
#: 两个访问器用例共用同一份，避免两处纪律再次走偏（手列清单已被证伪：13/24）。
_DIRTY_ALL = (
    "out.pristine = snap();\n"
    "__dirtyAll(cardState, '');\n"
    "out.dirty = snap();\n"
    "out.dirtyPaths = __dirtyPaths;\n"
)


def _assert_dirty_covers_all_leaves(out: Dict[str, Any]) -> None:
    """写脏步骤自检：覆盖率 == `EXPECTED_INITIAL`，且每个哨兵都与初值有别。

    两个失明点都在这里钉死：
    - 漏写一个叶子 ⇒ 该字段「写回初值」在前后 diff 里隐形（`prep.searchQuery = ""`
      / `quiz.correct = 0` 就是这么溜过去的）；
    - 哨兵恰好等于初值 ⇒ 同样隐形（脏了，但脏得看不出来）。
    """
    pristine = {path: _fingerprint(v) for path, v in _flatten(out["pristine"]).items()}
    dirtied = {path: _fingerprint(v) for path, v in _flatten(out["dirty"]).items()}

    assert sorted(pristine) == sorted(EXPECTED_INITIAL), (
        "写脏前的容器与本文件的期望表不一致\n"
        f"  缺失: {sorted(set(EXPECTED_INITIAL) - set(pristine))}\n"
        f"  多余: {sorted(set(pristine) - set(EXPECTED_INITIAL))}"
    )
    assert sorted(dirtied) == sorted(EXPECTED_INITIAL), (
        "写脏后叶子集合漂移（递归遍历漏掉/新增了字段）\n"
        f"  缺失: {sorted(set(EXPECTED_INITIAL) - set(dirtied))}\n"
        f"  多余: {sorted(set(dirtied) - set(EXPECTED_INITIAL))}"
    )

    reported = sorted(tuple(p.split(".")) for p in out["dirtyPaths"])
    assert len(out["dirtyPaths"]) == len(EXPECTED_INITIAL), (
        f"写脏路径数 {len(out['dirtyPaths'])} != 叶子数 {len(EXPECTED_INITIAL)}"
        "（有重复或遗漏 —— 手列清单就是这个下场）"
    )
    assert reported == sorted(EXPECTED_INITIAL), (
        "写脏步骤 MUST 覆盖全部 24 个叶子（漏掉的字段写回初值会隐形）\n"
        f"  漏写: {sorted(set(EXPECTED_INITIAL) - set(reported))}\n"
        f"  多写: {sorted(set(reported) - set(EXPECTED_INITIAL))}"
    )

    indistinct = sorted(path for path in pristine if pristine[path] == dirtied[path])
    assert indistinct == [], (
        f"这些叶子的哨兵与初值无差别（写回初值仍会隐形）: {indistinct}"
    )


def _assert_enter_segment_contract(out: Dict[str, Any]) -> None:
    """§2 用例的**全部判据**（`test_mutation_enter_segment_dropped_flipped_write` 复用同一份）。

    抽出来不是为了少写两行：变异自证要证明的是「§2 的这些断言会红」，若变异用例另写
    一套判据，它证明的只是「另一套判据会红」。
    """
    after = out["after"]
    _assert_dirty_covers_all_leaves(out)

    assert after["catalog"]["segment"] == "prep", "enterSegment 必须写 catalog.segment"
    assert after["deck"]["index"] == 0, "enterSegment 必须把 deck.index 复位为 0"
    assert after["deck"]["flipped"] is False, "enterSegment 必须把 deck.flipped 复位为 false"

    changed = _changed_paths(out["dirty"], after)
    assert changed == [
        ("catalog", "segment"),
        ("deck", "flipped"),
        ("deck", "index"),
    ], f"enterSegment 只许写这三处，实际改动: {changed}"


def test_enter_segment_writes_exactly_three_fields(tmp_path: Path) -> None:
    """`enterSegment('prep')` 只允许写 catalog.segment / deck.index / deck.flipped 三处。

    先把**全部 24 个叶子**写成哨兵（`__dirtyAll` 递归，不手列）再切段：初值全是
    0/false/""/null 时，「漏写一个复位」或「多写一个恰好等于初值的字段」在前后
    diff 里都完全隐形，该不变量就等于没人守。
    """
    out = _probe(tmp_path, _DIRTY_ALL + "enterSegment('prep');\nout.after = snap();\n")
    _assert_enter_segment_contract(out)


# ══ 3. stepDeckState：改动面恰好两处 ═════════════════════════════════════════


def test_step_deck_state_changes_exactly_two_fields(tmp_path: Path) -> None:
    """`stepDeckState(2)` 的改动路径集合 MUST 恰好是 {deck.index, deck.flipped}。

    与 `enterSegment` 同等纪律。只断言「index 数值对、flipped 变 false」是不够的：
    给 `stepDeck` 顺手加第三个写（`deck.lastFlipTime = Date.now()`，或写回初值的
    `deck.reviewInFlight = false`）在其余用例里全绿 —— 这条正是为「顺手多写一处」准备的。
    """
    out = _probe(
        tmp_path,
        _DIRTY_ALL
        + "cardState.deck.index = 4;\n"
        "cardState.deck.flipped = true;\n"
        "out.before = snap();\n"
        "stepDeckState(2);\n"
        "out.after = snap();\n",
    )
    after = out["after"]
    _assert_dirty_covers_all_leaves(out)

    assert after["deck"]["index"] == 6, f"deck.index 应 4+2=6，实际 {after['deck']['index']!r}"
    assert after["deck"]["flipped"] is False, "stepDeckState 必须把 deck.flipped 置 false"

    changed = _changed_paths(out["before"], after)
    assert changed == [("deck", "flipped"), ("deck", "index")], (
        f"stepDeckState 只许写 deck.index / deck.flipped 两处，实际改动: {changed}"
    )


# ══ 4. stepDeckState：不得夹取 ═══════════════════════════════════════════════


def _assert_step_deck_no_clamp(out: Dict[str, Any]) -> None:
    """§4 用例的全部判据（`test_mutation_step_deck_state_clamp` 复用同一份）。"""
    assert out["before"]["deck"]["index"] == 0
    assert out["afterNegative"]["deck"]["index"] == -1, (
        "stepDeckState(-1) 从 0 出发必须得到 -1（夹取到 0 是行为变更，不是加固）："
        f"实际 {out['afterNegative']['deck']['index']!r}"
    )
    assert out["afterPositive"]["deck"]["index"] == 100, (
        "stepDeckState(+1) 从 99 出发必须得到 100（夹取到 99 是行为变更）："
        f"实际 {out['afterPositive']['deck']['index']!r}"
    )


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
    _assert_step_deck_no_clamp(out)


# ══ 5. stepDeckState：复位翻面 ═══════════════════════════════════════════════


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


# ══ 6. L1 纯层：零顶层可变状态、零 import ═══════════════════════════════════


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


# ══ 7. 变异自证：每条不变量「拆掉机制就会红」 ═════════════════════════════════
#
# 前面几个任务各自**手工**做过一次「拆掉机制 ⇒ 用例变红」的验证（计划 Task 6）。手工
# 自证的半衰期是一次会话：结论留在记录里，判据不留在 CI 里。这一节把六次验证固化，
# 判据是「期望的规则名 / 期望的断言文本」，**不是** exit 非 0 —— 后者在探针因无关原因
# 崩掉时同样成立（本仓的「有故障、没结论」类）。
#
# 两条硬纪律：
#   1) 每条只碰 `tmp_path` 里的副本。真实树被改成「变异后忘了复原」是本套件最坏的
#      失败模式（用例还绿着，树已经坏了），故 `_gate_with_mutation` 每次调用都逐字节
#      对账一次，M4/M5/M6 各自再对账一次 sha256。
#   2) 断言必须**点名**：注入的行 / 被删的那个字段 / 容器的名字。只断言「红了」的
#      变异用例，在断言的判别力退化（例如某天被改成 `assert out`）时仍然全绿。


def _eol_of(src: str) -> str:
    """源码用的行尾（本仓静态文件是 CRLF；变异跟随原文，别在副本里掺出 lone LF）。"""
    return "\r\n" if "\r\n" in src else "\n"


def _sha256_of(rel: str) -> str:
    return hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest()


def _violations_naming(rendered: List[str], rule: str, needle: str) -> List[str]:
    """同时命中**规则名**与**对象文本**的违规行（只有规则名不算点名）。"""
    return [line for line in rendered if rule in line and needle in line]


def _gate_with_mutation(tmp_path: Path, module: str, mutate: Callable[[str], str]) -> List[str]:
    """把整棵 `static/js` 复制到 tmp、只变异副本、在副本上跑闸，回传 render() 后的违规行。

    复制而不是原地改：`static/js` 是真实树，本套件 MUST NOT 碰它（用例写错路径也只
    弄脏 tmp）。收尾把副本写回**原始字节**并与真实文件逐字节对账 —— 「变异只发生在
    副本里」不是口头承诺，每次调用都自证一遍。
    """
    src_dir = REPO_ROOT / JS_DIR_REL
    rel = f"{JS_DIR_REL}/{module}"
    before = _sha256_of(rel)
    real = src_dir / module

    js_dir = tmp_path / "js"
    shutil.copytree(src_dir, js_dir)

    original = real.read_bytes().decode("utf-8")
    mutated = mutate(original)
    assert mutated != original, f"变异没生效：{module} 的锚点已漂移（用例失效，不是实现变好）"

    target = js_dir / module
    target.write_bytes(mutated.encode("utf-8"))
    rendered = [v.render() for v in collect_violations(js_dir)]

    target.write_bytes(original.encode("utf-8"))
    assert target.read_bytes() == real.read_bytes(), f"{module} 副本未逐字节复原"
    assert _sha256_of(rel) == before, f"{rel} 真实文件被改动了（变异 MUST 只发生在副本里）"
    return rendered


def test_mutation_cards_js_top_level_let_is_caught(tmp_path: Path) -> None:
    """M1：`cards.js` 顶层重新长出 `let` ⇒ 闸 MUST 报 `零顶层可变状态契约禁mutable-state`。

    钉的是 `check_layer_bans` 的 **⑦**（只受可变状态契约约束、却不在 `LAYER_SPEC` 的
    模块）。⑦ 被删或被短路时，`cards.js` 那 15 处既有的可变状态钉子会**无声归零** ——
    这正是 Task 1 修掉的结构缺陷，也是本套件存在的理由。断言必须点名注入的那一行：
    只对规则名的话，「规则名对、但报到别的 `let` 上」也会溜过去。
    """
    injected = "let __mutation_top_level_state = 0;"
    rendered = _gate_with_mutation(
        tmp_path, "cards.js", lambda src: _eol_of(src).join([injected, src])
    )

    hits = _violations_naming(rendered, "零顶层可变状态契约禁mutable-state", injected)
    assert hits, (
        "cards.js 顶层长出 `let` 后，闸 MUST 报 `零顶层可变状态契约禁mutable-state` "
        f"并点名注入行；实际违规 {len(rendered)} 处: {rendered}"
    )
    assert len(rendered) == 1, (
        f"注入一行顶层 `let` 应恰好产生 1 处违规（不连坐），实际 {len(rendered)} 处: {rendered}"
    )


def test_mutation_cd_state_document_is_caught(tmp_path: Path) -> None:
    """M2：`cd-state.js` 里出现 `document.` ⇒ 闸 MUST 报 `L1 纯状态容器禁dom`。

    L1 纯层是「谁都能 import、谁都能读」的前提；状态容器一旦碰 DOM，它就不再能在
    node 里被真跑（本文件 §1-§5 的全部行为断言都建立在这一点上）。
    """
    injected = "const __mutation_dom_read = document.title;"
    rendered = _gate_with_mutation(
        tmp_path, "cd-state.js", lambda src: _eol_of(src).join([injected, src])
    )

    hits = _violations_naming(rendered, "L1 纯状态容器禁dom", injected)
    assert hits, (
        "cd-state.js 碰 `document` 后，闸 MUST 报 `L1 纯状态容器禁dom` "
        f"并点名注入行；实际违规 {len(rendered)} 处: {rendered}"
    )
    assert len(rendered) == 1, f"注入一行 DOM 读取应恰好 1 处违规，实际: {rendered}"


def test_mutation_cd_state_out_of_scope_import_is_caught(tmp_path: Path) -> None:
    """M3：`cd-state.js` 出现 `import { esc } from './core.js'` ⇒ MUST 报 `越界import`。

    `allowed_imports=()` 是「容器不依赖任何东西」的机械表达。`./core.js` 是 L1 兄弟层
    的合法 import（`wr-format.js` 就允许），所以这条**只能**靠白名单为空来挡 ——
    正是「看起来无害、其实越界」的那类漂移。
    """
    injected = "import { esc } from './core.js';"
    rendered = _gate_with_mutation(
        tmp_path, "cd-state.js", lambda src: _eol_of(src).join([injected, src])
    )

    hits = _violations_naming(
        rendered, "L1 纯状态容器越界import(core.js)", injected
    )
    assert hits, (
        "cd-state.js 越界 import 后，闸 MUST 报 `L1 纯状态容器越界import(core.js)` "
        f"并点名注入行；实际违规 {len(rendered)} 处: {rendered}"
    )
    assert len(rendered) == 1, f"注入一行越界 import 应恰好 1 处违规，实际: {rendered}"


def test_mutation_enter_segment_dropped_flipped_write_is_caught(tmp_path: Path) -> None:
    """M4：删掉 `enterSegment` 的 `cardState.deck.flipped = false` ⇒ §2 用例 MUST 红。

    「这行有人守」今天只是某次会话里手工删过一次看过的结论。此处把同一行在**副本**里
    删掉，再把 §2 的**同一份断言**（`_assert_enter_segment_contract`）跑一遍：必须抛
    AssertionError，且文本点名被删的那次写。落到「实际改动: […]」那种泛化措辞不算通过
    —— 它只说改动面少了一处，说不出少的是哪一处（何况字段名不在其中）。
    """
    before = _sha256_of(CD_STATE_REL)
    source = _cd_state_source()
    eol = _eol_of(source)
    anchor = f"  cardState.deck.index = 0;{eol}  cardState.deck.flipped = false;{eol}"
    assert source.count(anchor) == 1, (
        f"锚点应唯一（enterSegment 的三写），实际命中 {source.count(anchor)} 处：变异会误伤"
    )
    mutated = source.replace(anchor, f"  cardState.deck.index = 0;{eol}")

    out = _probe_source(
        tmp_path,
        mutated,
        _DIRTY_ALL + "enterSegment('prep');\nout.after = snap();\n",
        label=f"{CD_STATE_REL}（副本：删掉 deck.flipped 复位）",
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_enter_segment_contract(out)

    text = str(excinfo.value)
    assert "enterSegment 必须把 deck.flipped 复位为 false" in text, (
        "删掉 deck.flipped 复位后，§2 的用例 MUST 以**点名该字段**的断言红，"
        f"实际红在: {text!r}"
    )
    assert _sha256_of(CD_STATE_REL) == before, f"{CD_STATE_REL} 真实文件被改动了"


def test_mutation_step_deck_state_clamp_is_caught(tmp_path: Path) -> None:
    """M5：给 `stepDeckState` 加 `Math.max(0, …)` 夹取 ⇒ §4 用例 MUST 红。

    「顺手加固」是设计稿 §6.1 点名警告的行为变更（初稿的 `advanceDeck(delta, total)`
    自带夹取）。§4 的判据靠「越界必须如实越界」成立；此处加回夹取，验证那条断言真的
    在守 —— 而不是被 §3 的「改动面恰好两处」顺带盖住（夹取仍是两写，改动面不变，
    §3 对它**完全失明**）。
    """
    before = _sha256_of(CD_STATE_REL)
    source = _cd_state_source()
    anchor = "  cardState.deck.index += delta;"
    assert source.count(anchor) == 1, f"锚点应唯一，实际命中 {source.count(anchor)} 处"
    mutated = source.replace(
        anchor, "  cardState.deck.index = Math.max(0, cardState.deck.index + delta);"
    )

    out = _probe_source(
        tmp_path,
        mutated,
        "out.before = snap();\n"
        "stepDeckState(-1);\n"
        "out.afterNegative = snap();\n"
        "cardState.deck.index = 99;\n"
        "stepDeckState(1);\n"
        "out.afterPositive = snap();\n",
        label=f"{CD_STATE_REL}（副本：stepDeckState 夹取到 0）",
    )
    with pytest.raises(AssertionError) as excinfo:
        _assert_step_deck_no_clamp(out)

    text = str(excinfo.value)
    assert "stepDeckState(-1) 从 0 出发必须得到 -1" in text, (
        "加了夹取后，§4 的用例 MUST 以「越界被夹取是行为变更」的断言红，"
        f"实际红在: {text!r}"
    )
    assert _sha256_of(CD_STATE_REL) == before, f"{CD_STATE_REL} 真实文件被改动了"


def _run_node(script: Path, cwd: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["node", str(script), "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
    )


def test_mutation_probe_without_cd_state_seam_is_caught(tmp_path: Path) -> None:
    """M6：探针丢掉 cd-state.js 接缝 ⇒ 具名 exit 1（含容器名），不是裸 ReferenceError。

    计划 Task 6 的原写法是「删掉 `ia_dom_mount_probe` 的 `cardState` 桩」。那根桩在
    Task 5 已连同「手写同形桩」一起删除（两份真源并存本身就是假绿风险），所以等价的
    现存变异对象是**唯一形态**的接缝：`stateFn = sliceObjectDecl(cdStateJs, …)`。
    删掉它，`transformed` 里就没有 `cardState` 容器 —— 探针 MUST 自己说出
    `切片缺 cd-state.js 的 cardState 容器`，而不是让渲染切片在沙箱里抛裸 ReferenceError
    （后者是「有故障、没结论」：探针不知道自己在守护什么，读者也不知道该修哪）。
    """
    rel = "tools/cards_wb_source_probe.mjs"
    probe_before = _sha256_of(rel)
    js_before = _sha256_of(f"{JS_DIR_REL}/cards.js")
    state_before = _sha256_of(CD_STATE_REL)

    source = (REPO_ROOT / rel).read_bytes().decode("utf-8")
    seam = 'stateFn = sliceObjectDecl(cdStateJs, "export const cardState = ");'
    assert source.count(seam) == 1, f"{rel} 的 cd-state 接缝已漂移（命中 {source.count(seam)} 处）"
    mutated = source.replace(seam, "/* M6 变异：cd-state.js 接缝已删除 */")

    # 探针按 `__dirname/..` 解析 ROOT ⇒ 副本必须带一棵同形的 static/js。
    root = tmp_path / "probe_root"
    shutil.copytree(REPO_ROOT / JS_DIR_REL, root / JS_DIR_REL)
    (root / "tools").mkdir(parents=True)
    probe = root / rel

    # 基线：同一份副本不变异必须 exit 0，否则下面那句 exit≠0 归因不成立。
    probe.write_bytes(source.encode("utf-8"))
    baseline = _run_node(probe, root)
    assert baseline.returncode == 0, f"副本基线必须绿（否则 M6 归因不成立）:\n{baseline.stderr}"

    probe.write_bytes(mutated.encode("utf-8"))
    broken = _run_node(probe, root)
    combined = (broken.stdout or "") + (broken.stderr or "")

    assert broken.returncode != 0, f"删掉 cd-state 接缝后探针仍 exit 0（接缝无人守）:\n{combined}"
    assert "cd-state.js 的 cardState 容器" in combined, (
        f"探针 MUST 以**容器名**报错，实际输出: {combined!r}"
    )
    assert "    at " not in combined, (
        f"删掉接缝后 MUST 是具名契约失败，不是未捕获异常的栈（有故障、没结论）: {combined!r}"
    )
    assert _sha256_of(rel) == probe_before, f"{rel} 真实文件被改动了"
    assert _sha256_of(f"{JS_DIR_REL}/cards.js") == js_before
    assert _sha256_of(CD_STATE_REL) == state_before
