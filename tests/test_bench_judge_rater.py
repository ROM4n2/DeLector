# -*- coding: utf-8 -*-
"""`tools/bench_judge_rater.py` 的行为契约测试（Task 4：辅助仪器盲评 rater，**不进判决**）。

钉住什么（每条都对应一处可被抽掉的守卫）
--------------------------------------
1. **Rating 字段契约**：五项、名字与顺序逐字（计划 Task 4）。
2. **盲评顺序**：`order_seed` 确定性决定呈现顺序（"ba"/"ab" 两分支都实跑）；同一 seed 恒
   同序同请求；请求里两个中性槽位与 order 逐字对应。
3. **去盲映射**：用「按文本内容给分」的判别性 stub —— 两段文本换槽位后，Rating 的
   before/after 读数必须回正确的一侧（顺序倒过来读数不许跟着倒）。
4. **rubric 逐字一致**：两个顺序的 system 消息逐字节相同（只有文本槽位互换）。
5. **零归属泄漏**：发给模型的全文 MUST NOT 出现臂标签（a1_baseline/a2_no_signal/
   a3_current、A1/A2/A3）或「哪份是润色后/原文」的暗示词（黑名单逐条扫描，两序都扫）。
6. **auxiliary 隔离**：`insert_into_report` 只写 `report["auxiliary"]`（带 role 标记
   `auxiliary_signal_not_used_in_verdict`），`judgement_basis` 与 `arms` 逐字未变；写进
   评级后仍可 JSON 序列化；原 report 不被改动。与 `summarize` 真实产物对接另钉一条。
7. **零 Key / 无默认 chat**：源码不含 Key 载入路径、不 import delector；`chat` 是必填
   关键词参数；畸形回复 ⇒ ValueError（辅助信号宁缺勿假）。
8. **--dry-run 不触发 rater**：住 `tests/test_bench_judge_gaming.py`（同批钉住 socket 闸、
   `llm_client.chat` 闸与 Report 判决面不变）。

反挂死纪律：无 sleep / 无线程 / 无子进程；全部 stub（零 Key、零网络）。
"""

import dataclasses
import importlib.util
import inspect
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_RATER_SCRIPT = _ROOT / "tools" / "bench_judge_rater.py"
_GAMING_SCRIPT = _ROOT / "tools" / "bench_judge_gaming.py"

#: 判别性 stub 用的两段盲文（刻意互不为子串；不含任何黑名单词）：
#: before = 带语法错误的版本，after = 修好的版本；stub 按**内容**给分。
_BEFORE_TEXT = "Ich habe ein Apfel gekauft."
_AFTER_TEXT = "Ich habe einen Apfel gekauft."

#: 发给模型的全文里 MUST NOT 出现的词（臂标签 + 「哪份是润色后/原文」的暗示）。
_FORBIDDEN_TOKENS = (
    "a1_baseline",
    "a2_no_signal",
    "a3_current",
    "A1",
    "A2",
    "A3",
    "baseline",
    "no_signal",
    "current",
    "润色",
    "原文",
    "初稿",
    "底稿",
    "改后",
    "改写",
    "polished",
    "original",
    "before",
    "after",
)


def _load_module(name: str, path: Path) -> types.ModuleType:
    """按路径加载 tools/ 下的脚本（tools/ 不是 package，同 test_bench_judge_gaming.py）。

    MUST 先注册 `sys.modules`：被测脚本用 `from __future__ import annotations`，
    dataclasses 在 exec 期会查 `sys.modules[cls.__module__]` 解析字符串注解。
    两个被测模块用**不同**的装载名（同一 pytest 会话里互不覆盖）。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"脚本不存在或不可装载：{path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rater = _load_module("bench_judge_rater_under_test", _RATER_SCRIPT)
_gaming = _load_module("bench_judge_gaming_under_test_r4", _GAMING_SCRIPT)


def _slot_texts(user: str) -> tuple[str, str]:
    """按「Text 1: …／Text 2: …」的中性槽位口径取两段盲文（盲评请求的呈现协议即规约）。"""
    one = user.index("Text 1:")
    two = user.index("Text 2:")
    assert one < two, "Text 1 槽必须先于 Text 2 槽（呈现协议）"
    return user[one + len("Text 1:"):two].strip(), user[two + len("Text 2:"):].strip()


class StubChat:
    """**判别性** stub chat（零 Key、零网络）：记录每次请求，按「文本内容」给分。

    评分只认文本内容本身（`_BEFORE_TEXT` ⇒ correctness 2 / idiomatic 1；
    `_AFTER_TEXT` ⇒ 4 / 5）：只要 rater 的去盲映射错了，Rating 的 before/after 读数
    就会跟着错 —— 顺序分支因此可被逐字测到。`model_name` 与真 chat 包装器同形。
    """

    model_name = "rater-stub"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        scores_by_text = {
            _BEFORE_TEXT: {"correctness": 2, "idiomatic": 1},
            _AFTER_TEXT: {"correctness": 4, "idiomatic": 5},
        }
        user = str(kwargs["messages"][-1]["content"])
        first, second = _slot_texts(user)
        return {
            "text1": dict(scores_by_text[first]),
            "text2": dict(scores_by_text[second]),
        }


def _fixed_chat(reply: Any) -> Any:
    """返回固定回复的 stub chat（畸形回复用例用）。"""

    class _Chat:
        model_name = "rater-stub"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def __call__(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return reply

    return _Chat()


# ── Rating 字段契约与盲评顺序 ────────────────────────────────────────────────


def test_rating_field_contract_is_exact() -> None:
    """Rating 恰好五项、名字与顺序逐字固定（计划 Task 4 的字段面；JSON 键即此名）。"""
    assert [field.name for field in dataclasses.fields(rater.Rating)] == [
        "correctness_before",
        "correctness_after",
        "idiomatic_before",
        "idiomatic_after",
        "order",
    ]


def test_rate_pair_presents_in_seed_determined_order_both_branches() -> None:
    """`order_seed` 确定性决定顺序：偶数 ⇒ "ba"（先 before）；奇数 ⇒ "ab"（先 after）。

    两个分支都实跑：既钉 order 值，也钉请求里两个盲槽与 order 的逐字对应；同 seed 恒同序
    同请求（同输入同输出）。
    """
    for seed, expected_order in ((0, "ba"), (2, "ba"), (1, "ab"), (3, "ab")):
        chat = StubChat()
        rating = rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=seed, chat=chat)
        assert rating.order == expected_order
        first, second = _slot_texts(chat.calls[-1]["messages"][-1]["content"])
        if expected_order == "ba":
            assert (first, second) == (_BEFORE_TEXT, _AFTER_TEXT)
        else:
            assert (first, second) == (_AFTER_TEXT, _BEFORE_TEXT)

    chat_a, chat_b = StubChat(), StubChat()
    first_run = rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=7, chat=chat_a)
    second_run = rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=7, chat=chat_b)
    assert first_run == second_run
    assert chat_a.calls == chat_b.calls


def test_rate_pair_unblinds_scores_in_both_orders() -> None:
    """去盲映射：stub 按文本内容给分（before ⇒ 2/1，after ⇒ 4/5）——两段文本换槽位后，
    Rating 的 before/after 读数必须回正确的一侧（顺序倒过来，读数不许跟着倒）。"""
    for seed in (0, 1):  # 0 ⇒ "ba"；1 ⇒ "ab"
        rating = rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=seed, chat=StubChat())
        assert (rating.correctness_before, rating.correctness_after) == (2, 4)
        assert (rating.idiomatic_before, rating.idiomatic_after) == (1, 5)


def test_rate_pair_rubric_is_identical_across_orders_and_call_shape_matches_loop() -> None:
    """两个顺序的 rubric（system 消息）逐字节一致；一对文本恰好一次调用；调用形制与
    `polish_loop` 的 chat 调用同形（Task 5/6 接 `llm_client.chat` 时天然兼容）。"""
    chat_ba, chat_ab = StubChat(), StubChat()
    rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=0, chat=chat_ba)
    rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=1, chat=chat_ab)
    assert len(chat_ba.calls) == 1 and len(chat_ab.calls) == 1

    systems = [chat_ba.calls[0]["messages"][0], chat_ab.calls[0]["messages"][0]]
    assert systems[0] == systems[1]
    assert systems[0] == {"role": "system", "content": rater.RATER_SYSTEM_PROMPT}

    call = chat_ba.calls[0]
    assert call["model"] == ""  # 注入 chat 时不读配置（与 run_polish_loop 同约定）
    assert call["response_format"] == {"type": "json_object"}
    assert isinstance(call["timeout"], float) and call["timeout"] > 0
    assert isinstance(call["max_tokens"], int) and call["max_tokens"] > 0


def test_request_carries_no_arm_attribution_hints() -> None:
    """发给模型的**任何内容**不得出现臂标签或「哪份是原文/润色后」的暗示（两序都扫）。

    单行变异自证靶点：往 `_pair_messages` 的 user 内容里塞一个臂标签（如
    `Text 1（a3_current 的润色候选）:`）⇒ 本用例立红（黑名单命中）。
    """
    for seed in (0, 1):
        chat = StubChat()
        rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=seed, chat=chat)
        payload = json.dumps(chat.calls[0]["messages"], ensure_ascii=False)
        for token in _FORBIDDEN_TOKENS:
            assert token not in payload, f"盲评请求泄漏了归属信息：{token!r}"
        # 正对照：中性槽位标记必须在场（否则黑名单扫的是空壳）
        assert "Text 1" in payload and "Text 2" in payload
        # 两段文本各出现恰好一次（不许出现「第三份」）
        assert payload.count(_BEFORE_TEXT) == 1
        assert payload.count(_AFTER_TEXT) == 1


def test_rate_pair_rejects_malformed_replies_and_empty_text() -> None:
    """畸形回复 ⇒ ValueError（辅助信号宁缺勿假：畸形分不得静默变 0 分混进报告）；
    空文本 ⇒ ValueError。"""
    valid_slot = {"correctness": 2, "idiomatic": 1}
    bad_replies = [
        {"text1": valid_slot},  # 缺 text2 槽
        {"text1": valid_slot, "text2": {"correctness": 7, "idiomatic": 5}},  # 越界分
        {"text1": {"correctness": "zwei", "idiomatic": 1}, "text2": valid_slot},  # 非整数
        "不是 JSON 对象",  # 整体形状不合法
    ]
    for reply in bad_replies:
        with pytest.raises(ValueError):
            rater.rate_pair(_BEFORE_TEXT, _AFTER_TEXT, order_seed=0, chat=_fixed_chat(reply))
    with pytest.raises(ValueError):
        rater.rate_pair("", _AFTER_TEXT, order_seed=0, chat=StubChat())
    with pytest.raises(ValueError):
        rater.rate_pair(_BEFORE_TEXT, "   ", order_seed=0, chat=StubChat())


# ── auxiliary 隔离（Task 4 的核心 MUST） ─────────────────────────────────────


def _verdict_fixture_report() -> dict[str, Any]:
    """带三臂全判决字段的固定 Report（数值手写；不跑任何真实链路，**不含** auxiliary 键）。"""
    metrics = {
        "runs": 2,
        "R_judge": 0.5,
        "R_uncovered": 0.25,
        "rollback_rate": 0.0,
        "new_errors": 1,
        "tokens_total": 120,
        "elapsed_p50": 0.25,
        "elapsed_p95": 0.75,
        "rounds_mean": 2.0,
    }
    return {
        "judgement_basis": "uncovered_seed_recovery",
        "arms": {arm: dict(metrics) for arm in ("a1_baseline", "a2_no_signal", "a3_current")},
    }


def test_insert_into_report_writes_only_auxiliary_and_keeps_verdicts_verbatim() -> None:
    """auxiliary 隔离（MUST）：写评级后 `judgement_basis` 与 `arms` 逐字未变；role 标记在场；
    原 report 不被改动；写进评级后的 Report 仍可 JSON 序列化。

    变异自证靶点：让 `insert_into_report` 顺手写一处判决字段（如把 judgement_basis 改写成
    角色标记）⇒ 本用例立红。
    """
    report = _verdict_fixture_report()
    basis_before = json.dumps(report["judgement_basis"], ensure_ascii=False)
    arms_before = json.dumps(report["arms"], ensure_ascii=False, sort_keys=True)
    ratings = [
        rater.Rating(correctness_before=2, correctness_after=4, idiomatic_before=1, idiomatic_after=5, order="ba"),
        rater.Rating(correctness_before=3, correctness_after=3, idiomatic_before=2, idiomatic_after=2, order="ab"),
    ]

    merged = rater.insert_into_report(report, ratings)

    # ① 判决面逐字未变（本用例的目的）；② 只在原键集上**新增** auxiliary
    assert json.dumps(merged["judgement_basis"], ensure_ascii=False) == basis_before
    assert json.dumps(merged["arms"], ensure_ascii=False, sort_keys=True) == arms_before
    assert set(merged) == set(report) | {"auxiliary"}
    assert "auxiliary" not in report and json.dumps(report["arms"], sort_keys=True) == arms_before

    # ③ role 标记逐字在场；④ ratings 以 JSON 友好形态落进 auxiliary
    assert merged["auxiliary"]["role"] == "auxiliary_signal_not_used_in_verdict"
    assert merged["auxiliary"]["role"] == rater.AUXILIARY_ROLE
    assert merged["auxiliary"]["ratings"] == [
        {
            "correctness_before": 2,
            "correctness_after": 4,
            "idiomatic_before": 1,
            "idiomatic_after": 5,
            "order": "ba",
        },
        {
            "correctness_before": 3,
            "correctness_after": 3,
            "idiomatic_before": 2,
            "idiomatic_after": 2,
            "order": "ab",
        },
    ]
    # ⑤ 写进评级后的 Report 可序列化（O3 钉的延伸）
    assert json.loads(json.dumps(merged, ensure_ascii=False)) == merged


def test_insert_into_report_fills_summarize_auxiliary_slot() -> None:
    """与 harness 真实 Report 对接：`summarize` 的 `auxiliary=None` 槽（未运行 rater 的
    形态）被评级填上后，判决面逐字不变、槽位形状为 {role, ratings}。"""
    report = _gaming.summarize([], [])
    assert set(report) == {"judgement_basis", "arms", "auxiliary"}
    assert report["auxiliary"] is None
    arms_before = json.dumps(report["arms"], ensure_ascii=False, sort_keys=True)

    merged = rater.insert_into_report(report, [])

    assert merged["judgement_basis"] == report["judgement_basis"] == _gaming.JUDGEMENT_BASIS
    assert json.dumps(merged["arms"], ensure_ascii=False, sort_keys=True) == arms_before
    assert merged["auxiliary"] == {"role": rater.AUXILIARY_ROLE, "ratings": []}
    assert report["auxiliary"] is None  # 原 report 仍是「未运行」形态


# ── 零 Key 红线（产物级 tripwire） ───────────────────────────────────────────


def test_rater_module_has_no_key_path_and_no_default_chat() -> None:
    """rater 源码不得出现任何 Key 载入路径、不得 import delector/httpx（真 chat 接线属
    Task 5/6）；`rate_pair` 的 `chat` 是**必填关键词**参数（没有默认真 chat）。"""
    source = _RATER_SCRIPT.read_text(encoding="utf-8")
    needles = (
        "load_env(",
        "get_effective_api_key",
        "DEEPSEEK_API_KEY",
        "from delector",
        "import delector",
        "httpx",
    )
    for needle in needles:
        assert needle not in source, f"rater 源码不得出现：{needle!r}"
    signature = inspect.signature(rater.rate_pair)
    assert list(signature.parameters) == ["before", "after", "order_seed", "chat"]
    chat_param = signature.parameters["chat"]
    assert chat_param.kind is inspect.Parameter.KEYWORD_ONLY
    assert chat_param.default is inspect.Parameter.empty


# ── Task 4（B5）⑥：rater 可执行入口（结构冒烟 CLI；零 Key、零网络） ─────────────


def test_rater_module_exposes_executable_main_entry() -> None:
    """⑥ rater 有可执行入口：`main(argv)` 可调用 + 源码含 `__main__` guard（交付物清单的一项）。

    `--help` 与输出头都标 stub（不冒充真盲评）；入口仍零 Key / 无默认 chat。
    """
    assert callable(rater.main)
    source = _RATER_SCRIPT.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert "raise SystemExit(main())" in source
    assert "stub" in source  # 如实标注结构冒烟，不冒充真盲评


def test_rater_main_runs_structural_smoke_over_pairs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """⑥ `main`：读 `--pairs` ⇒ 跑盲评管线（stub）⇒ 输出 role + ratings 的 JSON；ret 0。

    逐对 `order_seed + index` 轮换（0 ⇒ ba、1 ⇒ ab）—— 由 `--order-seed` 决定起点。
    """
    pairs = [
        {"id": "p0", "before": _BEFORE_TEXT, "after": _AFTER_TEXT},
        {"id": "p1", "before": _AFTER_TEXT, "after": _BEFORE_TEXT},
    ]
    path = tmp_path / "pairs.json"
    path.write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")

    rc = rater.main(["--pairs", str(path)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["role"] == rater.AUXILIARY_ROLE
    assert [entry["id"] for entry in out["ratings"]] == ["p0", "p1"]
    assert out["ratings"][0]["order"] == "ba"
    assert out["ratings"][1]["order"] == "ab"

    rc2 = rater.main(["--pairs", str(path), "--order-seed", "1"])
    out2 = json.loads(capsys.readouterr().out)
    assert rc2 == 0
    assert out2["ratings"][0]["order"] == "ab"  # 起点右移一位 ⇒ 首对变 ab


def test_rater_main_bad_input_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """⑥ 输入不可用（文件不存在 / 形状不合法）⇒ 退 2（人话；不猜、不静默丢对）。"""
    assert rater.main(["--pairs", str(tmp_path / "nope.json")]) == 2
    assert "输入不可用" in capsys.readouterr().err

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"id": "x"}]), encoding="utf-8")  # 缺 before/after
    assert rater.main(["--pairs", str(bad)]) == 2
    assert "输入不可用" in capsys.readouterr().err