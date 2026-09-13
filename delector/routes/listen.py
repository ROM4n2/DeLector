# -*- coding: utf-8 -*-
"""听力微训工坊 API（/api/listen，Task 3）。

材料聚合（encounter 分级短文 + a1_hoeren 音频句库）+ 切句详情 + 本地听写诊断 +
成绩落盘。diagnose/trials 为本地单用户数据，非敏感，不挂 _require_localhost 闸
（红线 7 写操作分类纪律）；材料端点纯只读。
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from delector.core.database import (
    get_encounter_text,
    list_encounter_texts,
    list_listen_trials,
    record_listen_trial,
)
from delector.data.a1_hoeren_dict import get_hoeren_set_by_id, get_hoeren_set_list
from delector.nlp_engine.syntax_tree import split_sentences_pure_python
from delector.services.listen import ListenDiagnosis, diagnose_diktat

router = APIRouter(prefix="/api/listen", tags=["listen"])

# hoeren 套题全部为歌德 A1 官方真题，材料 level 固定（题组数据无等级字段）
_HOEREN_LEVEL = "A1"


class DiagnoseRequest(BaseModel):
    """听写诊断请求：期望句 vs 实际输入句。"""

    expected: str
    actual: str


class ListenTrialRequest(BaseModel):
    """听力微训成绩落盘请求：会话汇总字段（score 由服务端按 correct/total 计算）。"""

    mode: str
    source_type: str
    source_id: int
    level: str
    total: int
    correct: int
    duration_sec: int


def _hoeren_materials() -> List[Dict[str, object]]:
    """hoeren 音频句库材料列表：每套题一个材料，title 用题组德语标题。"""
    return [
        {
            "source_type": "hoeren",
            "source_id": s["set_id"],
            "title": s["title_de"],
            "level": _HOEREN_LEVEL,
        }
        for s in get_hoeren_set_list()
    ]


def _encounter_materials(level: Optional[str]) -> List[Dict[str, object]]:
    """encounter 短文材料列表：title/level 直取表字段。"""
    return [
        {
            "source_type": "encounter",
            "source_id": r["id"],
            "title": r["title"],
            "level": r["level"],
        }
        for r in list_encounter_texts(level=level)
    ]


def _collect_hoeren_sentences(data: Dict[str, object]) -> List[str]:
    """从一套 hoeren 题面收集 audio_text_de 切句（红线 10：只走 split_sentences_pure_python）。"""
    sentences: List[str] = []
    parts = data["parts"]
    assert isinstance(parts, dict)
    for part_name in ("teil_1", "teil_2", "teil_3"):
        for q in parts.get(part_name, []):
            assert isinstance(q, dict)
            sentences.extend(split_sentences_pure_python(str(q.get("audio_text_de") or "")))
    return sentences


@router.get("/materials")
def api_listen_materials(level: Optional[str] = None):
    """材料聚合：encounter 短文 + hoeren 音频句库；level 为空返回全部。"""
    items = _encounter_materials(level=level)
    if not level or level == _HOEREN_LEVEL:
        items.extend(_hoeren_materials())
    return {"items": items}


@router.get("/materials/{source_type}/{source_id}")
def api_listen_material_detail(source_type: str, source_id: int):
    """材料详情：content/题面切句后的句子列表；材料不存在 → 404 人话。"""
    if source_type == "encounter":
        row = get_encounter_text(source_id)
        if not row:
            raise HTTPException(status_code=404, detail="短文不存在")
        title, level = row["title"], row["level"]
        sentences = [s for s in split_sentences_pure_python(row["content"]) if s]
    elif source_type == "hoeren":
        data = get_hoeren_set_by_id(source_id, sanitize=True)
        if not data:
            raise HTTPException(status_code=404, detail="听力套题不存在")
        title, level = data["title_de"], _HOEREN_LEVEL
        sentences = [s for s in _collect_hoeren_sentences(data) if s]
    else:
        raise HTTPException(status_code=404, detail="未知材料类型")
    return {
        "source_type": source_type,
        "source_id": source_id,
        "title": title,
        "level": level,
        "sentences": sentences,
    }


@router.post("/diagnose")
def api_listen_diagnose(req: DiagnoseRequest) -> ListenDiagnosis:
    """本地听写诊断：纯本地调用 diagnose_diktat，无 DB 无联网，不挂闸。"""
    return diagnose_diktat(req.expected, req.actual)


@router.post("/trials")
def api_listen_record_trial(req: ListenTrialRequest):
    """听力微训成绩落盘：本地单用户记录，非敏感，不挂闸。score=correct/total。"""
    score = req.correct / req.total if req.total else 0.0
    trial_id = record_listen_trial(
        mode=req.mode,
        source_type=req.source_type,
        source_id=req.source_id,
        level=req.level,
        total=req.total,
        correct=req.correct,
        score=score,
        duration_sec=req.duration_sec,
    )
    return {"trial_id": trial_id}


@router.get("/trials")
def api_listen_trials(limit: int = 50):
    """听力微训历史：created_at 倒序，limit 上限 100（钳制在 database 层）。"""
    return {"items": list_listen_trials(limit=limit)}
