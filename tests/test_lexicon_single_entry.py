# -*- coding: utf-8 -*-
"""Task R6：词汇主干单入口化守卫（ADR-0012 §5-3）。

静态扫描源码文本（``pathlib`` 读 ``.py`` 原文 + 正则，**不 import 被测模块**），钉死
「消费端不得直连分片」这一架构不变量：

- 违规 = 任何 ``from delector.data.{core_dict,core_dict_ext,official_vocab} import ...``
  或 ``import delector.data.{core_dict,core_dict_ext,official_vocab}``（直连分片）。
- 白名单 = 主干 ``delector/core/lexicon.py`` 与分片宿主 ``delector/data/*``
  （它们是分片的合法 import 点，主干对外 API 亦在 lexicon re-export）。

扫描范围 = ``delector/`` 全部 ``.py``（**包含**计划点名的 routes/services/nlp_engine/tools
与 ``core/database.py``，并有意做成其超集）—— 这样白名单才有意义、且未来新模块直连分片会被拦。

反恒真自检：把检测逻辑抽成模块级纯函数 :func:`find_direct_shard_imports`，并用一段**含违规**
的假文本断言检测能命中、再对合法文本断言不命中 —— 防止「扫描范围写错 → 恒为空 → 假绿」。
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_ROOT = _REPO_ROOT / "delector"

# 禁直连的分片模块（主干 ``delector.core.lexicon`` 是唯一合法入口）。
_SHARD_MODULES = ("core_dict", "core_dict_ext", "official_vocab")
_SHARD_ALT = "|".join(_SHARD_MODULES)

# 违规模式：``from delector.data.<shard> import ...`` 或 ``import delector.data.<shard>``。
_SHARD_IMPORT_RE = re.compile(
    rf"^\s*(?:from\s+delector\.data\.(?:{_SHARD_ALT})\s+import\b"
    rf"|import\s+delector\.data\.(?:{_SHARD_ALT})\b)"
)


def find_direct_shard_imports(source_text: str) -> list:
    """返回源码文本中「直连分片」的违规行号（1-based）。

    纯函数、零 IO、不 import 任何 delector 模块 —— 供守卫扫描与反向自检共用同一段逻辑，
    保证「扫描器本身」被测试覆盖（否则扫描器写错会静默假绿）。
    """
    return [i for i, line in enumerate(source_text.splitlines(), start=1) if _SHARD_IMPORT_RE.match(line)]


def is_whitelisted(rel_path: str) -> bool:
    """白名单：主干 ``delector/core/lexicon.py`` 与分片宿主 ``delector/data/*``。

    ``rel_path`` 用仓库根相对 POSIX 路径（正斜杠）。
    """
    rel = rel_path.replace("\\", "/")
    if rel == "delector/core/lexicon.py":
        return True
    return rel.startswith("delector/data/")


def _iter_scanned_sources():
    """遍历 ``delector/`` 下全部 ``.py``（跳过白名单），产出 ``(相对路径, 源码文本)``。"""
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if is_whitelisted(rel):
            continue
        yield rel, path.read_text(encoding="utf-8")


# ── 交付 4 主断言：消费端零直连分片 ─────────────────────────────────────────


def test_no_direct_shard_import_outside_whitelist():
    """``delector/``（除白名单）不得直连分片；列出全部违规点便于定位。"""
    violations = []
    for rel, text in _iter_scanned_sources():
        for lineno in find_direct_shard_imports(text):
            violations.append(f"{rel}:{lineno}")
    assert not violations, "消费端直连分片（应经 delector.core.lexicon）：" + ", ".join(violations)


def test_whitelisted_hosts_are_the_only_exempt_paths():
    """白名单精确性：主干与分片宿主被豁免，其它路径（含 database.py）不被豁免。"""
    assert is_whitelisted("delector/core/lexicon.py")
    assert is_whitelisted("delector/data/core_dict.py")
    assert is_whitelisted("delector/data/core_dict_ext.py")
    assert is_whitelisted("delector/data/official_vocab.py")
    # 非白名单：这些必须被扫描（含计划点名文件）
    assert not is_whitelisted("delector/core/database.py")
    assert not is_whitelisted("delector/routes/main.py")
    assert not is_whitelisted("delector/services/writing.py")
    assert not is_whitelisted("delector/nlp_engine/processor.py")
    assert not is_whitelisted("delector/nlp_engine/linguistics.py")
    assert not is_whitelisted("delector/tools/vocab_stats.py")


def test_plain_import_of_shards_is_also_forbidden():
    """``import delector.data.core_dict_ext`` / ``official_vocab`` 亦属违规（非仅 from 形式）。"""
    for stmt in (
        "import delector.data.core_dict_ext",
        "import delector.data.official_vocab",
        "from delector.data.official_vocab import OFFICIAL_VOCAB",
    ):
        assert find_direct_shard_imports(stmt) == [1], stmt


# ── 反恒真自检：检测器对违规/合规文本必须给出相反判定 ────────────────────────


def test_detector_flags_synthetic_violation():
    """含违规的假文本必须被判定为违规（防「扫描恒空」的假绿死断言）。"""
    fake_violation = "import os\nfrom delector.data.core_dict import CORE_VOCAB_DB\n"
    assert find_direct_shard_imports(fake_violation) == [2]


def test_detector_accepts_synthetic_clean_text():
    """合法文本（经主干 lexicon 取词）必须判定为合规 —— 与上一条形成对照。"""
    fake_clean = (
        "import os\n"
        "from delector.core.lexicon import CORE_VOCAB_DB, lookup_core_vocab\n"
        "x = 1\n"
    )
    assert find_direct_shard_imports(fake_clean) == []


def test_detector_distinguishes_extends_from_base_module():
    """``core_dict`` 与 ``core_dict_ext`` 两列都判违规，且不误伤相似的合法模块名。"""
    assert find_direct_shard_imports("from delector.data.core_dict_ext import CORE_VOCAB_EXT") == [1]
    # 相似但不违规：lexicon / lexicon_merge 不是分片
    assert find_direct_shard_imports("from delector.data.lexicon_merge import merge_fragments") == []
