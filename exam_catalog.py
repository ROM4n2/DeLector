"""Exam catalog 目录注册表（ADR-0005 Task 3）—— 等级→模块 的导航单源。

设计决策（用户已拍板）：
- **题库数据不入 SQLite**：本文件是「代码注册目录」。加一个等级 =
  在 EXAM_CATALOG 插一个 key（配合数据模块常量），未来 A2 立项即插行。
- **只引用数据模块的常量，不复制数据**：count 通过 count_fn 从数据模块
  实时推导。**防失败面仅限常量访问**：模块级 `import a1_dict` 等仍是
  硬依赖（模块被删/改名 import 期即崩，server 起不来）；单个 count_fn
  抛错（常量重命名、数据坏形）→ count 记 0 + logger.warning 留痕，
  catalog 端点与 server 启动均不受牵连。
- **旧 /api/a1/* 端点不迁移**：catalog 只做导航发现（api_prefix 指向
  既有取题端点前缀），panel 指向 index.html 里的面板容器 id。
"""
import logging
from typing import Any, Callable, Dict, List, Optional

import a1_dict
import a1_hoeren_dict
import a1_lesen_dict
import a1_writing_dict
from database import get_vocab_by_cefr

logger = logging.getLogger("delector")

# count_fn: 零参调用返回该模块题量。try/except 覆盖「数据模块常量改名」
# 场景（模块 import 仍为硬依赖，见 docstring）：常量缺失时 count 记 0
# 且 logger.warning 记录异常——零静默吞异常（测试
# test_catalog_survives_broken_count_fn 钉住 count 行为）。
EXAM_CATALOG: Dict[str, Dict[str, Any]] = {
    "A1": {
        "title": "A1",
        "modules": {
            "writing": {
                "title": "📝 写作专项 (Schreiben)",
                "panel": "exam-writing",
                "api_prefix": "/api/a1",
                "count_fn": lambda: (
                    len(a1_writing_dict.A1_SCHREIBEN_TEIL1_EXERCISES)
                    + len(a1_writing_dict.A1_SCHREIBEN_TEIL2_PROMPTS)
                ),
            },
            "hoeren": {
                "title": "🎧 听力模考 (Hörverstehen)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a1",
                "count_fn": lambda: len(a1_hoeren_dict.A1_HOEREN_SETS),
            },
            "lesen": {
                "title": "📖 阅读工坊 (Leseverstehen)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a1",
                "count_fn": lambda: len(a1_lesen_dict.A1_LESEN_SETS),
            },
            "sprechen": {
                "title": "💬 口语问答 (Sprechen)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a1",
                "count_fn": lambda: (
                    len(a1_dict.A1_SPRECHEN_TEIL2) + len(a1_dict.A1_SPRECHEN_TEIL3)
                ),
            },
            "vocab": {
                "title": "📖 官方考纲词表 (Wortliste)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a1",
                "count_fn": lambda: len(a1_dict.GOETHE_A1_VOCAB),
            },
        },
    },
    "A2": {
        "title": "A2",
        "modules": {
            "vocab": {
                "title": "📖 官方考纲词表 (Wortliste)",
                "panel": "exam-cards-family",
                "api_prefix": "/api/a2",
                "count_fn": lambda: len(get_vocab_by_cefr("A2")["words"]),
            },
        },
    },
}


def _safe_count(count_fn: Optional[Callable[[], int]]) -> int:
    """count 推导失败（数据模块常量重命名/缺常量）→ 记 0 并 warning 留痕。"""
    if count_fn is None:
        return 0
    try:
        return int(count_fn())
    except Exception:
        logger.warning("[exam-catalog] 模块题量推导失败，count 记 0", exc_info=True)
        return 0


def get_catalog() -> Dict[str, Any]:
    """序列化 catalog：{"levels": [{"id", "title", "modules": [
    {"id", "title", "panel", "api_prefix", "count"}]}]}。

    count_fn 是 Python 可调用、不可 JSON 化，故此层负责把注册表扁平化为
    纯数据（count 取 _safe_count 结果）。等级顺序 = 注册序（dict 插入序）。
    返回 fresh dict，调用方随意改。
    """
    levels: List[Dict[str, Any]] = []
    for lid, reg in EXAM_CATALOG.items():
        modules = [
            {
                "id": mid,
                "title": mod.get("title", mid),
                "panel": mod.get("panel", ""),
                "api_prefix": mod.get("api_prefix", ""),
                "count": _safe_count(mod.get("count_fn")),
            }
            for mid, mod in reg.get("modules", {}).items()
        ]
        levels.append({"id": lid, "title": reg.get("title", lid), "modules": modules})
    return {"levels": levels}
