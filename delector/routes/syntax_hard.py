# -*- coding: utf-8 -*-
"""长难句精读工坊 API（/api/syntax，Task 3）。

材料聚合（articles 文章正文 + encounter 分级短文）→ rank_sentences 跨语料难度榜 +
单句完整分析（detail，供前端揭示渲染 clause_tree/topology）+ 训练记录落盘。
trials 为本地单用户训练记录，非敏感，不挂 _require_localhost 闸（红线 7）；
hard-sentences 列表/detail 纯只读。

性能纪律（规格 §4）：全文逐句分析是重计算（spaCy ~42ms/句）——进程内存缓存
（键=source+id，TTL 300s，容量上限 256 条）防重复计算 + limit 护栏（默认 50 上限 100）
+ 按需懒算（材料正文仅缓存缺失时读，聚合只取 id 不 materialize 全文）。
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from delector.core.database import (
    db_conn,
    get_encounter_text,
    list_hard_sentence_trials,
    record_hard_sentence_trial,
)
from delector.nlp_engine.syntax_tree import (
    analyze_syntax_tree,
    get_spacy_load_error,
    get_spacy_nlp,
    split_sentences_pure_python,
)
from delector.services.syntax_score import _detect_path, rank_sentences, score_sentence

router = APIRouter(prefix="/api/syntax", tags=["syntax"])

# 排名结果内存缓存：键 = "source:id"，值 = (过期时刻, items 全量)。
# 存放**未过滤未截断**的全量 items（过滤/limit 在读取时应用），TTL 内同材料
# 不重复跑 analyze_syntax_tree（红线 10 切句 + spaCy 逐句分析的重计算）。
# 缓存值 = (过期时刻, items 全量)，显式类型让 _rank_source 的读取免 Any 回落。
_RANK_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_CACHE_TTL_SEC = 300.0
# 容量上限（2026-09-28 swarm 审计）：长期运行材料不断增删时缓存条目只增不减会缓慢
# 泄漏内存；超限按**最早过期优先**淘汰（TTL 相同时近似插入序 LRU，新写入的必不被淘汰）。
_RANK_CACHE_MAX_ENTRIES = 256


def _put_rank_cache(key: str, expires: float, items: List[Dict[str, Any]]) -> None:
    """写入排名缓存；超出容量上限时淘汰最早过期的一条，防长期运行内存无界增长。"""
    _RANK_CACHE[key] = (expires, items)
    if len(_RANK_CACHE) > _RANK_CACHE_MAX_ENTRIES:
        oldest = min(_RANK_CACHE, key=lambda k: _RANK_CACHE[k][0])
        _RANK_CACHE.pop(oldest, None)


# --follow-imports=skip 下 pydantic 无 stub，BaseModel 为 Any，无法做子类化检查，豁免 misc
class HardSentenceTrialRequest(BaseModel):
    """长难句训练记录落盘请求：会话汇总字段（level/score/revealed 由前端传入）。"""

    source: str
    source_id: int
    sentence_index: int
    level: str
    score: float
    revealed: int
    duration_sec: int


def _material_text(source: str, source_id: int) -> str:
    """按 source 取材料正文；材料不存在/来源非法 → 404 人话。"""
    if source == "article":
        with db_conn() as conn:
            row = conn.execute("SELECT raw_text FROM articles WHERE id = ?", (source_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="文章不存在")
        # sqlite 行对象无 stub 为 Any，取列值无法静态确认类型，豁免 no-any-return
        return row["raw_text"]  # type: ignore[no-any-return]
    if source == "encounter":
        row = get_encounter_text(source_id)
        if not row:
            raise HTTPException(status_code=404, detail="短文不存在")
        # get_encounter_text 跨模块导入被 skip 为 Any，取列值免 Any 回落豁免
        return row["content"]  # type: ignore[no-any-return]
    raise HTTPException(status_code=404, detail="未知材料来源")


def _rank_source(source: str, source_id: int) -> List[Dict[str, Any]]:
    """单材料的句子难度榜（含缓存）；sentence_index 对齐原文切句序号。

    材料正文**仅在缓存缺失时**才读（2026-09-28 swarm 审计）：`source=all` 每请求
    重新 materialize 全部正文是多余 I/O —— 热请求直接命中缓存、完全不碰正文。

    红线 10：切句只走 split_sentences_pure_python（与 rank_sentences 内部同一切句
    实现，句子一一对应）；rank_sentences 降序后按句子文本回填原始序号（重复句取
    首现位置，前端 reveal 同句不影响训练闭环）。
    """
    key = f"{source}:{source_id}"
    now = time.monotonic()
    cached = _RANK_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]
    # 材料缺失 → 404 向上传播（单材料直查需要；source=all 由调用方按材料隔离）。
    text = _material_text(source, source_id)
    # 红线 1/纪律：切句与分析同属可失败路径——与 rank_sentences 的逐句容错对齐，
    # 单材料整体失败返回空榜（不炸调用方，source=all 逐材料隔离依赖这里）。
    try:
        sents = split_sentences_pure_python(text)
    except Exception:
        _put_rank_cache(key, now + _CACHE_TTL_SEC, [])
        return []
    idx_of: Dict[str, int] = {}
    for i, s in enumerate(sents):
        idx_of.setdefault(s, i)
    items: List[Dict[str, Any]] = []
    for r in rank_sentences(text):
        items.append(
            {
                "sentence": r.sentence,
                "score": r.score,
                "level": r.level,
                "dimensions": r.dimensions,
                "path": r.path,
                "source": source,
                "source_id": source_id,
                "sentence_index": idx_of.get(r.sentence, 0),
            }
        )
    _put_rank_cache(key, now + _CACHE_TTL_SEC, items)
    return items


def _list_article_ids() -> List[int]:
    """全部文章 id（source=all 难度榜聚合用）；只取 id，不 materialize 正文。"""
    with db_conn() as conn:
        rows = conn.execute("SELECT id FROM articles ORDER BY id").fetchall()
        return [int(r["id"]) for r in rows]


def _list_encounter_ids() -> List[int]:
    """全部 encounter 短文 id（source=all 聚合用）；只取 id，不 materialize 正文。"""
    with db_conn() as conn:
        rows = conn.execute("SELECT id FROM encounter_texts ORDER BY id DESC").fetchall()
        return [int(r["id"]) for r in rows]


@router.get("/spacy-status")# --follow-imports=skip 下 fastapi 装饰器为 Any
def api_syntax_spacy_status() -> Dict[str, Any]:
    """spaCy 加载诊断（v5.7.4：无 adb 时在 App 内定位 Android 走 pure 的原因）。

    返回当前实际路径（spacy/pure）与加载失败的具体异常；成功加载时 error 为空。
    纯只读、非敏感，供前端「轻量分析」提示旁展示定位信息。
    """
    return {"path": "spacy" if get_spacy_nlp() else "pure", "error": get_spacy_load_error() or ""}


@router.get("/hard-sentences")# 同上：fastapi 装饰器为 Any
def api_syntax_hard_sentences(
    source: str = "all",
    source_id: Optional[int] = None,
    level: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """跨语料句子难度榜：source ∈ article/encounter/all；level/min_score 过滤 + limit 护栏。"""
    src = (source or "all").lower()
    if src not in ("article", "encounter", "all"):
        raise HTTPException(status_code=404, detail="未知材料来源")
    lim = max(1, min(int(limit), 100))
    if src == "all":
        items: List[Dict[str, Any]] = []
        # 逐材料隔离：任一材料切句/分析异常只丢该材料，不炸整榜（纪律同 _rank_source）
        try:
            art_ids = _list_article_ids()
        except Exception:
            art_ids = []
        for aid in art_ids:
            try:
                items.extend(_rank_source("article", aid))
            except Exception:
                continue
        try:
            enc_ids = _list_encounter_ids()
        except Exception:
            enc_ids = []
        for eid in enc_ids:
            try:
                items.extend(_rank_source("encounter", eid))
            except Exception:
                continue
        # 各材料内部已降序，跨材料合并后须整体按难度降序（难度榜契约）
        items.sort(key=lambda it: it["score"], reverse=True)
    else:
        items = _rank_source(src, int(source_id or 0))
    if level:
        level_norm = level.strip().upper()
        items = [it for it in items if it["level"] == level_norm]
    if min_score is not None:
        items = [it for it in items if it["score"] >= min_score]
    return {"items": items[:lim]}


@router.get("/hard-sentences/detail")# 同上：fastapi 装饰器为 Any
def api_syntax_hard_sentences_detail(source: str, source_id: int, sentence_index: int) -> Dict[str, Any]:
    """单句完整分析：analysis 含 clause_tree/topology（供前端揭示渲染）；越界/缺失/分析失败 404。"""
    src = (source or "").lower()
    text = _material_text(src, source_id)
    sents = split_sentences_pure_python(text)
    if sentence_index < 0 or sentence_index >= len(sents):
        raise HTTPException(status_code=404, detail="句子序号越界")
    sent = sents[sentence_index]
    # 红线 1/纪律：单句分析是可失败路径（Android spaCy/数据差异下 analyze_syntax_tree
    # 可能抛）——与 rank_sentences 逐句容错对齐，失败降级 404 人话而非 500。
    try:
        analysis = analyze_syntax_tree(sent)
        batch = analysis.get("sentences")
        if not isinstance(batch, list) or not batch:
            raise HTTPException(status_code=404, detail="该句暂无法分析")
        single = batch[0]
        scored = score_sentence(single, path=_detect_path(single))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="该句暂无法分析") from None
    return {
        "sentence": sent,
        "score": scored.score,
        "level": scored.level,
        "dimensions": scored.dimensions,
        "path": scored.path,
        "analysis": single,
    }


@router.post("/hard-sentence/trials")# 同上：fastapi 装饰器为 Any
def api_syntax_record_trial(req: HardSentenceTrialRequest) -> Dict[str, Any]:
    """长难句训练记录落盘：本地单用户记录，非敏感，不挂闸（红线 7）。"""
    trial_id = record_hard_sentence_trial(
        source=req.source,
        source_id=req.source_id,
        sentence_index=req.sentence_index,
        level=req.level,
        score=req.score,
        revealed=req.revealed,
        duration_sec=req.duration_sec,
    )
    return {"trial_id": trial_id}


@router.get("/hard-sentence/trials")# 同上：fastapi 装饰器为 Any
def api_syntax_hard_trials(limit: int = 50) -> Dict[str, Any]:
    """长难句训练历史：created_at 倒序，limit 上限 100（钳制在 database 层）。"""
    return {"items": list_hard_sentence_trials(limit=limit)}
