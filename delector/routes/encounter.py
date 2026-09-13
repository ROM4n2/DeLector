# -*- coding: utf-8 -*-
"""`/api/encounter/*` 路由（遇见区 i+1 Task A2）。

提供四类能力：
- GET 列表 / 详情（读 encounter_texts，word_count 由服务端按空白分词算，跑不上 spaCy）
- POST 手工加文本（限本机）：title/level/source/content → 201
- POST import-pack（限本机）：把 job#1 的 encounter-pack/v1 整包落库成一篇短文

跨边界契约 `encounter-pack/v1` 定在本模块（`CARD_PACK_SCHEMA` + `validate_pack`）：
A/B 两端共同遵守这份 schema 定义。import 落库复用一个跨任务约定的语义：本机
pack_id 已存在时幂等返回既有行 id（不新增），因此同一包重复 POST 只会产生一行。

word_count = 简单空白分词计数（服务端 cheap 计算），不做 spaCy。
"""

import copy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from delector.core.database import (
    _require_localhost,
    create_encounter_text,
    get_encounter_text,
    import_encounter_pack,
    list_encounter_texts,
)
from delector.nlp_engine import process_german_text

router = APIRouter(prefix="/api/encounter", tags=["Encounter"])

# encounter-pack/v1 契约常量：A/B 侧共同校验的 schema 版本。
CARD_PACK_SCHEMA = "encounter-pack/v1"

# 建议阅读等级白名单（与表契约一致）。
_ALLOWED_LEVELS = ("A1", "A2", "B1")


class CreateTextRequest(BaseModel):
    title: str = Field(min_length=1)
    level: str = "A2"
    source: str = ""
    content: str = Field(min_length=1)


class ImportPackRequest(BaseModel):
    pack: dict


def _normalize_level(raw: str, field_name: str = "level") -> str:
    """把输入的 level 规一到白名单内的大写 A1/A2/B1，非法抛 HTTPException(400)。"""
    normalized = (raw or "").strip().upper()
    if normalized not in _ALLOWED_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} 仅支持 {'/'.join(_ALLOWED_LEVELS)}，收到: {raw!r}",
        )
    return normalized


def _count_words(content: str) -> int:
    """word_count：按空白分词（服务端 cheap 计算，不跑 spaCy）。"""
    return len(content.split())


def validate_pack(pack) -> None:
    """校验一个 encounter-pack/v1 卡包的结构（不校验 estimated_cefr —— 那在路由归一）。

    与 A1 import_encounter_pack 的 guard 语义一致：缺必需键抛 ValueError，文案用中文。
    仅做结构必需校验，不触碰估计等级（归一/白名单由路由层负责）。
    """
    if not isinstance(pack, dict):
        raise ValueError("pack 必须是 dict")
    if pack.get("schema") != CARD_PACK_SCHEMA:
        raise ValueError(f"pack.schema 必须为 {CARD_PACK_SCHEMA!r}，收到: {pack.get('schema')!r}")
    pack_id = pack.get("pack_id")
    if not pack_id or not str(pack_id).strip():
        raise ValueError("pack.pack_id 必填且不能为空")
    article = pack.get("article")
    if article is None or not isinstance(article, dict):
        raise ValueError("pack.article 必须是 dict 且必填")
    if not article.get("title") or not str(article["title"]).strip():
        raise ValueError("pack.article.title 必填且不能为空")
    if not article.get("raw_text") or not str(article["raw_text"]).strip():
        raise ValueError("pack.article.raw_text 必填且不能为空")


def _to_list_payload(row: dict) -> dict:
    """把 store 行压缩成列表端点所需的元数据（不含 content/pack_json）。"""
    return {
        "id": row["id"],
        "title": row["title"],
        "level": row["level"],
        "source": row["source"],
        "word_count": _count_words(row["content"] or ""),
        "created_at": row["created_at"],
    }


@router.get("/texts")
def api_list_texts(level: Optional[str] = None) -> dict:
    """遇见区短文列表：可传 ?level=A2 过滤，含服务端算的 word_count。"""
    rows = list_encounter_texts(level=level)
    return {"texts": [_to_list_payload(r) for r in rows]}


@router.get("/texts/{text_id:int}")
def api_get_text(text_id: int) -> dict:
    """取单篇短文（含 content / pack_json），缺失 404。"""
    row = get_encounter_text(text_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"短文未找到: {text_id}")
    return {
        "id": row["id"],
        "title": row["title"],
        "level": row["level"],
        "source": row["source"],
        "content": row["content"],
        "pack_json": row["pack_json"],
    }


def _annotate_tokens(sent_payload: dict) -> list:
    """把 process_german_text 产出的单句 tokens 映射成 annotate 需要的
    {text, lemma, pos}（标点也保留，前端自行过滤）；跳过纯空白伪 token。"""
    out = []
    for tok in sent_payload.get("tokens", []):
        if tok.get("is_space"):
            continue
        out.append({"text": tok["text"], "lemma": tok["lemma"], "pos": tok["pos"]})
    return out


@router.get("/texts/{text_id:int}/annotate")
def api_annotate_text(text_id: int) -> dict:
    """逐句逐 token 注解（lemma + 粗粒度 POS），前端据此做已背词匹配。

    读取 encounter_texts 正文，跑 spaCy（P0 直跑、禁缓存）。sentence idx 0-based
    顺序；total_tokens = 各句 token 数之和。文本缺失 404。

    零漂移保证：复用 process_german_text 产出的 tokens（已含 text/lemma/pos），
    只做映射、不改其返回结构 —— analyze 契约不受影响（test_tools.py 钉住）。
    """
    row = get_encounter_text(text_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"短文未找到: {text_id}")

    parsed = process_german_text(row["content"] or "")
    sentences = [{"idx": s["id"], "tokens": _annotate_tokens(s)} for s in parsed["sentences"]]
    total_tokens = sum(len(s["tokens"]) for s in sentences)
    return {
        "text_id": text_id,
        "total_tokens": total_tokens,
        "sentences": sentences,
    }


@router.post("/texts", status_code=201, dependencies=[Depends(_require_localhost)])
def api_create_text(req: CreateTextRequest) -> dict:
    """本机新增一篇手工短文，返回 {id,title,level}。"""
    level = _normalize_level(req.level)
    new_id = create_encounter_text(
        title=req.title.strip(),
        level=level,
        source=req.source or "",
        content=req.content,
    )
    return {"id": new_id, "title": req.title.strip(), "level": level}


@router.post("/import-pack", dependencies=[Depends(_require_localhost)])
def api_import_pack(req: ImportPackRequest) -> dict:
    """把 encounter-pack/v1 整包落库成一篇短文。

    落库前先本地校验结构 + 把 estimated_cefr 规一到白名单大写（A1/A2/B1）。
    幂等语义在存储层：同一 pack_id 重复 POST 返回既有行 id、不新增行 —— 见
    database.import_encounter_pack 注释。这里 `imported` 恒为 True 是文档化选择：
    存储层幂等已保证"不产生重复行"，上层无需再自造 pre-read 探测；要证幂等就看
    import-pack 重复调用返回同一 id 且列表行数不增（测试钉这条）。
    """
    pack = req.pack
    try:
        validate_pack(pack)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    raw_level = str(pack.get("estimated_cefr") or "A2").strip()
    normalized_level = _normalize_level(raw_level, field_name="estimated_cefr")

    # A1 import_encounter_pack 从 pack["estimated_cefr"] 取 level 落库，不接受独立
    # level 参数。要存规一化后的大写值，得在入库前改写 pack 副本（保持 db 层不动）。
    normalized_pack = copy.deepcopy(pack)
    normalized_pack["estimated_cefr"] = normalized_level
    new_id = import_encounter_pack(normalized_pack)
    return {"id": new_id, "imported": True}
