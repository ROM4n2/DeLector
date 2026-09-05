# -*- coding: utf-8 -*-
"""扩词库与查词链修复的测试：core_dict 合并 / 现在时反查 / EXT 接线。"""
import os

os.environ.setdefault("DATABASE_PATH", "test_delector.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_progress.db")

from core_dict import CORE_VOCAB_DB  # noqa: E402
from linguistics import lookup_irregular_verb, lookup_linguistics_ext  # noqa: E402


def test_merged_dict_module_loads():
    """core_dict_ext 已合并进 CORE_VOCAB_DB，总量远超原 443。"""
    assert len(CORE_VOCAB_DB) >= 3000


def test_generated_lemma_has_definition():
    """抽查生成词库词元（senioren）有非空中文释义。"""
    entry = CORE_VOCAB_DB.get("senioren")
    assert entry and entry[4]


def test_base_handcurated_wins_on_conflict():
    """合并冲突时 base 手编词条优先（dict 合并顺序 {**ext, **base}）。"""
    entry = CORE_VOCAB_DB["gehen"]
    assert entry and entry[4]  # gehen 仍在且非空


def test_irregular_present_index():
    """现在时高频形式能反查不定式（_AUX_MODAL_PRESENT 拓宽）。"""
    assert lookup_irregular_verb("ist").infinitiv == "sein"
    assert lookup_irregular_verb("geht").infinitiv == "gehen"
    assert lookup_irregular_verb("tut").infinitiv == "tun"


def test_linguistics_ext_lookup():
    """LINGUISTICS_VOCAB_EXT 走 lookup_linguistics_ext 可查（主链接线）。"""
    hit = lookup_linguistics_ext("klima")
    assert hit and hit["source"] == "linguistics_ext"
    assert "气候" in hit["definition_zh"]
    assert lookup_linguistics_ext("zzzznope") is None
