# -*- coding: utf-8 -*-
"""长难句精读工坊 API（/api/syntax，Task 3）。

材料聚合（articles 文章正文 + encounter 分级短文）→ rank_sentences 跨语料难度榜 +
单句完整分析（detail，供前端揭示渲染 clause_tree/topology）+ 训练记录落盘。
trials 为本地单用户训练记录，非敏感，不挂 _require_localhost 闸（红线 7）；
hard-sentences 列表/detail 纯只读。

性能纪律（规格 §4）：全文逐句分析是重计算（spaCy ~42ms/句）——进程内存缓存
（键=source+id，TTL 300s，容量上限 256 条）防重复计算 + limit 护栏（默认 50 上限 100）
+ 按需懒算（材料正文仅缓存缺失时读，聚合只取 id 不 materialize 全文）。
source=all 额外走**聚合层缓存**（整榜一个 key，见 _ALL_RANK_CACHE_KEY）：材料数
一过 256，逐材料条目就会被淘汰策略打穿（命中率悬崖），整榜一个 key 则与材料数无关。
"""

import threading
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
# source=all 的**聚合层**缓存键：整榜一个 key（2026-10-03 Task 1）。
# 逐材料条目各占一个 key，材料数一过 256 就会触发「最早过期优先」淘汰的悬崖
# （expires 逐条递增 + id 升序遍历 ⇒ 第 257 条起淘汰最早写的那批 ⇒ 下一轮全 miss）。
# 锁不能解悬崖（那是策略问题不是竞态），动态上限会把悬崖换成内存随语料线性增长
# （本地单用户 SQLite 更差）⇒ 整榜一个 key 是唯一同时解两者的手段。
# key 作用域：与语言/筛选无关（当前 source=all 无其它筛选参数）；将来加筛选 MUST 进 key。
_ALL_RANK_CACHE_KEY = "all"
# 保护 _RANK_CACHE 的**读-判-写整段**（读、判超限、min、pop）。
# 不加锁时 min() 迭代期间另一线程写入 ⇒ RuntimeError: dictionary changed size
# during iteration ⇒ 被 source=all 的 except Exception: continue 吞掉 ⇒
# 该材料静默从难度榜消失（结果错，不只是性能问题）。只锁 pop 那一行正是竞态本身。
_RANK_CACHE_LOCK = threading.Lock()


def _get_rank_cache(key: str) -> Optional[List[Dict[str, Any]]]:
    """锁保护下读排名缓存；未命中或已过期返回 None（调用方负责重算）。

    命中判定（expires > now）与读取在同一把锁内完成，避免"读到一半被并发淘汰/改写"。
    """
    now = time.monotonic()
    with _RANK_CACHE_LOCK:
        cached = _RANK_CACHE.get(key)
        if cached is None or not cached[0] > now:
            return None
        return cached[1]


def _put_rank_cache(key: str, expires: float, items: List[Dict[str, Any]]) -> None:
    """写入排名缓存；超出容量上限时淘汰最早过期的一条，防长期运行内存无界增长。

    锁覆盖"写入 + 判超限 + min + pop"**整段**（不只是 pop）：min() 必须在锁内完成，
    否则并发写会在迭代中途改 dict 大小 → RuntimeError。
    淘汰策略（最早过期优先）不变 —— tests/test_syntax_hard_api.py 的
    test_rank_cache_bounded_eviction 钉住该语义。
    """
    with _RANK_CACHE_LOCK:
        _RANK_CACHE[key] = (expires, items)
        if len(_RANK_CACHE) > _RANK_CACHE_MAX_ENTRIES:
            oldest = min(_RANK_CACHE, key=lambda k: _RANK_CACHE[k][0])
            _RANK_CACHE.pop(oldest, None)


def _drop_rank_cache_except(key: str) -> None:
    """删掉除 key 外的全部缓存条目（聚合层 sweep 收尾用，锁内整段执行）。

    聚合层已覆盖整榜，逐材料条目留着只会在后续 min() 淘汰时被误伤（甚至把聚合 key
    之外的空位占满，导致单材料路径无谓重算）。MUST NOT 清掉 key 本身。
    """
    with _RANK_CACHE_LOCK:
        for k in [k for k in _RANK_CACHE if k != key]:
            del _RANK_CACHE[k]


def invalidate_rank_cache() -> None:
    """材料写入/删除后失效聚合层缓存（source=all 整榜，2026-10-03 Task 1 收尾）。

    **为什么必须有这个入口**：聚合 key 的 TTL 是 300s，而基线行为是"新材料入库 ⇒
    下次 sweep 立即可见 / 材料删除 ⇒ 下次 sweep 自然消失"。没有失效入口时，新入库
    文章在聚合 key 命中期间**最长 300 秒不出现在难度榜**，已删材料**滞留 300 秒**
    ——与 Task 1 修的"材料静默从难度榜消失"是同一类缺陷（结果错，不是性能问题），
    只是被 TTL 兜底且自愈。写入点（ingest/delete/create_encounter_text）都是单条
    操作、非批处理，故每次成功后调一次即可。

    **MUST 在锁内做**：与 _put_rank_cache 的 "写 + 判超限 + min + pop" 整段同一把锁。
    无锁时本函数的 pop 与并发 _put_rank_cache 的 min() 迭代相撞 ⇒ RuntimeError:
    dictionary changed size during iteration ⇒ 被 source=all 的 except Exception:
    continue 吞掉 ⇒ 材料静默从难度榜消失（竞态，见 _RANK_CACHE_LOCK 注释）。

    **幂等**：pop 用 default=None，聚合 key 不存在时不抛——同一批材料的多次写入
    会连续触发本函数，失效入口不允许成为写入路径的失败源。

    取舍：**只清聚合 key，不连带清逐材料条目**。聚合层已整榜覆盖逐材料条目（sweep
    收尾的 _drop_rank_cache_except 还会把它们清掉），故只清聚合 key 就是最小动作；
    连带清逐材料条目会白丢单材料路径（source=article&source_id=）与 detail 邻接路径
    的热缓存，而那次写入/删除与那些材料无关。聚合 key 失效后重聚合本就会重新写它们。
    """
    with _RANK_CACHE_LOCK:
        _RANK_CACHE.pop(_ALL_RANK_CACHE_KEY, None)


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
    cached_items = _get_rank_cache(key)
    if cached_items is not None:
        return cached_items
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
        # 聚合层缓存（2026-10-03 Task 1）：整榜一个 key，命中直接返回，材料数再大
        # 也不会被 _RANK_CACHE_MAX_ENTRIES 的淘汰策略打穿（见 _ALL_RANK_CACHE_KEY 注释）。
        # 注意过滤（level/min_score/limit）在读取时应用，缓存里存的是未过滤未截断全量。
        agg = _get_rank_cache(_ALL_RANK_CACHE_KEY)
        if agg is None:
            merged: List[Dict[str, Any]] = []
            # 逐材料隔离：任一材料切句/分析异常只丢该材料，不炸整榜（纪律同 _rank_source）。
            # 聚合层 MUST 复用这条隔离语义，MUST NOT 放宽成"整体失败"。
            try:
                art_ids = _list_article_ids()
            except Exception:
                art_ids = []
            for aid in art_ids:
                try:
                    merged.extend(_rank_source("article", aid))
                except Exception:
                    continue
            try:
                enc_ids = _list_encounter_ids()
            except Exception:
                enc_ids = []
            for eid in enc_ids:
                try:
                    merged.extend(_rank_source("encounter", eid))
                except Exception:
                    continue
            # 各材料内部已降序，跨材料合并后须整体按难度降序（难度榜契约）
            merged.sort(key=lambda it: it["score"], reverse=True)
            _put_rank_cache(_ALL_RANK_CACHE_KEY, time.monotonic() + _CACHE_TTL_SEC, merged)
            # 收尾：逐材料条目被聚合层覆盖，清掉（留着只会在后续 min() 淘汰时被误伤）
            _drop_rank_cache_except(_ALL_RANK_CACHE_KEY)
            agg = merged
        items = agg
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
