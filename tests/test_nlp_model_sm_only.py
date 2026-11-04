# -*- coding: utf-8 -*-
"""NLP 模型档位单一事实源守卫（ADR-0027，2026-11-04）。

背景：`processor` 曾按 `("de_core_news_md", "de_core_news_sm")` 顺序加载，但全链路
（CI、自动下载、Android 打包、uv 环境）实际只有 `sm`。"md 优先"从未生效，只是被
`sm` 静默兜底 —— 代码与运行事实不符。ADR-0027 定案只支持 `sm`，本文件把它钉成机械契约：

1. 单一事实源：只有 `SPACY_MODEL_NAME = "de_core_news_sm"`，候选元组与独立的
   `AUTO_DOWNLOAD_MODEL` 双口径不再存在；
2. 运行期加载与自动下载共用同一常量，`md` 永不参与决策；
3. 失败语义不退化：本地无模型时 `try_load_nlp_no_download()` 返回 `None` 且**不下载**，
   自动下载路径失败则硬失败（不静默降级到纯 Python）。
"""

import re
from pathlib import Path
from typing import Any, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROCESSOR = REPO_ROOT / "delector" / "nlp_engine" / "processor.py"
SYNTAX_TREE = REPO_ROOT / "delector" / "nlp_engine" / "syntax_tree.py"
SM = "de_core_news_sm"


def test_processor_exposes_single_sm_model_source() -> None:
    """模型名只有一个真相源；候选元组与独立下载口径都已删除。"""
    from delector.nlp_engine import processor

    assert processor.SPACY_MODEL_NAME == SM
    assert not hasattr(processor, "SPACY_MODEL_CANDIDATES"), (
        "ADR-0027 已定案只支持 sm：不得再保留 md/sm 候选元组（否则会重新引入 md 优先）"
    )
    assert not hasattr(processor, "AUTO_DOWNLOAD_MODEL"), (
        "ADR-0027 要求运行期与自动下载同名同源：不得再保留独立的 AUTO_DOWNLOAD_MODEL"
    )


def test_runtime_modules_do_not_reference_md() -> None:
    """运行期两个加载器不得再出现 md 包名（防止有人把优先分支加回来）。"""
    for path in (PROCESSOR, SYNTAX_TREE):
        text = path.read_text(encoding="utf-8")
        assert "de_core_news_md" not in text, (
            f"{path.name} 仍引用 de_core_news_md：ADR-0027 只支持 sm，md 分支不得回潮"
        )


def test_syntax_tree_uses_shared_constant() -> None:
    """`syntax_tree.get_spacy_nlp()` 必须复用 processor 的常量，而不是自己写字面量。"""
    text = SYNTAX_TREE.read_text(encoding="utf-8")
    assert "SPACY_MODEL_NAME" in text, "syntax_tree 未复用 processor.SPACY_MODEL_NAME（双事实源）"
    assert not re.search(r'spacy\.load\("de_core_news_\w+"\)', text), (
        "syntax_tree 里出现了硬编码模型名字面量：应复用 SPACY_MODEL_NAME 单一事实源"
    )


def test_tooling_has_no_md_package_reference() -> None:
    """`tools/` 下的可执行基准/脚本不得引用 md 包名或已删除的候选常量（历史叙述可保留 md 字样）。"""
    offenders = [
        path.name
        for path in (REPO_ROOT / "tools").glob("*.py")
        if "de_core_news_md" in path.read_text(encoding="utf-8")
        or "SPACY_MODEL_CANDIDATES" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"tools 仍引用 md 模型或已删除的候选常量：{offenders}"


def test_autodownload_loads_only_sm(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地能加载时，第一次尝试就是 sm，且不触发任何 md 尝试。"""
    from delector.nlp_engine import processor

    calls: List[str] = []

    def fake_load(name: str) -> Any:
        calls.append(name)
        return object(), name

    monkeypatch.setattr(processor, "_load_spacy_model", fake_load)
    _, how = processor._load_model_with_autodownload()

    assert calls == [SM], f"自动下载路径尝试了非 sm 模型：{calls}"
    assert how == SM


def test_autodownload_failure_is_loud_and_single_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """本地加载失败时只对同一个 sm 下载一次；再失败必须抛 RuntimeError（不静默降级）。"""
    import spacy.cli

    from delector.nlp_engine import processor

    load_calls: List[str] = []
    download_calls: List[str] = []

    def failing_load(name: str) -> Any:
        load_calls.append(name)
        raise RuntimeError("model missing")

    monkeypatch.setattr(processor, "_load_spacy_model", failing_load)
    monkeypatch.setattr(spacy.cli, "download", lambda name: download_calls.append(name))

    with pytest.raises(RuntimeError) as excinfo:
        processor._load_model_with_autodownload()

    assert load_calls == [SM, SM], f"加载尝试不应包含 md：{load_calls}"
    assert download_calls == [SM], f"自动下载不应包含 md：{download_calls}"
    assert SM in str(excinfo.value)


def test_no_download_path_returns_none_without_downloading(monkeypatch: pytest.MonkeyPatch) -> None:
    """桌面润色的中间态：本地加载失败就诚实返回 None，绝不退到下载路径。"""
    import spacy.cli

    from delector.nlp_engine import processor

    load_calls: List[str] = []

    def failing_load(name: str) -> Any:
        load_calls.append(name)
        raise RuntimeError("model missing")

    monkeypatch.setattr(processor, "_nlp_model", None)
    monkeypatch.setattr(processor, "_nlp_resolved", False)
    monkeypatch.setattr(processor, "_load_spacy_model", failing_load)
    download_calls: List[str] = []
    monkeypatch.setattr(spacy.cli, "download", lambda name: download_calls.append(name))

    assert processor.try_load_nlp_no_download() is None
    assert load_calls == [SM], f"本地加载尝试不应包含 md：{load_calls}"
    assert not download_calls, f"try_load_nlp_no_download 触发了下载：{download_calls}"
