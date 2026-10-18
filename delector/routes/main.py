# -*- coding: utf-8 -*-
"""主路由：原 server.py 里直接挂在 `app` 上的通用 handler（ADR-0008 Phase 1 Task 4）。

server.py 曾 2400 行：8 个分域 router 之外，还有 ~60 个 handler、FSRS/SM-2 算法、
TTS 生成、完形填空生成器、备份还原……全挤在一个模块里。本模块把它们整体接过来，
`server.py` 只剩"建 app、挂中间件、挂路由、挂静态目录"这四件事。

搬迁纪律（避免踩回旧坑）：

1. 这里是**纯搬迁**：handler 主体逐字搬来，只把装饰器 `@app.` 换成 `@router.`。
   语义改动应该在搬迁之后单独提交，否则"逻辑改坏了"和"搬错了"混在一起没法查。
2. 模块内仍用 `from delector.X import Y` 的绝对导入。**不要用相对导入**——
   `routes/a1.py` 搬迁时 `from .utils import _attachment_headers` 就从
   `delector.core.utils` 悄悄改指到不存在的 `delector.routes.utils`，只在真跑到那个
   端点时才 ModuleNotFoundError（本地测试曾因此红过一次）。
3. `delector.server` 不再 re-export 这些 handler 层符号；需要单测算法的测试
   直接从 `delector.routes.main` 取。monkeypatch 也必须打在**调用方模块**上，
   打在旧的 `delector.server.*` 上不再生效（那是搬迁期最容易静默失效的一类）。
"""

# mypy: disable-error-code="misc,untyped-decorator"
# 仅 --follow-imports=skip 校验模式下 pydantic/fastapi 被降级为 Any 才误报
# （BaseModel 子类化 / @router 装饰器）；正常 import 跟随下两错误码在本模块从不触发。

import asyncio
import contextlib
import functools
import json
import logging
import re
import threading
from datetime import datetime
from typing import Any, AsyncIterator, Callable, Dict, List, NamedTuple, Optional

import httpx as httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from delector.core.database import (
    AUDIO_CACHE_DIR as AUDIO_CACHE_DIR,
)
from delector.core.database import (
    _require_localhost,
    add_prep_saved,
    db_conn,
    get_all_corpus_syntax_stats,
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    get_prep_saved,
    ingest_article,
    log_study_event,
    upsert_corpus_syntax_stats,
)
from delector.core.lexicon import lookup_core_vocab
from delector.core.security import (
    PRESET_FEEDS,
    clean_html_to_article,
    fetch_remote_html,
    is_safe_public_url,
    parse_rss_feed,
)
from delector.core.utils import _attachment_headers
from delector.core.version import APP_VERSION

# X-WB-Key 鉴权单一实现（信令 sync/rtc + 本模块的 PUT /api/wb/state 共用一份，
# 杜绝「改一处漏一处 = 鉴权绕过」）。只依赖 database，不成环。
# 惰性加载后 NLP_ENGINE / NLP_ENGINE_DETAIL 会在**首次真正需要 NLP 时**被回填（成功仍 "spacy"、
# 失败改 "spacy(加载失败)"）。若像旧写法那样 `from ... import NLP_ENGINE` 按值取，字符串被**按值
# 拷贝**，回填对 route 不可见 ⇒ /api/settings 永远报导入期声明值（v5.7.6 真机确诊同类坑）。
# 故这里改取**模块对象**，在 handler 内 live 读，让「失败=硬失败」的真实状态能被读到。
from delector.nlp_engine import processor as _nlp_processor
from delector.nlp_engine.linguistics import (
    build_prep_matrix,
    lookup_irregular_verb,
    lookup_linguistics_ext,
    lookup_prep_collocations,
    split_komposita,
)
from delector.nlp_engine.processor import (
    PROCESSED_JSON_VERSION,
    SYSTEM_GRAMMAR_PROMPT,
    get_cefr_level,
    nlp,
    process_german_text,
)
from delector.nlp_engine.syntax_tree import analyze_syntax_tree

# 直接指到子模块而非 `from delector.routes import …`：本模块由 routes/__init__.py 导入，
# 走包子属性会撞上半初始化状态。
# 材料写入/删除后失效长难句聚合榜缓存（source=all 整榜，TTL 300s）。只导入失效入口
# （纯 dict pop + 锁），不引 syntax_hard 的其余重依赖；syntax_hard 本身不 import
# routes.*，故此处顶层导入无环。
from delector.routes.audio import (
    _TTS_CONCURRENCY_LIMIT as _TTS_CONCURRENCY_LIMIT,
)
from delector.routes.audio import (
    _TTS_SEMAPHORE as _TTS_SEMAPHORE,
)
from delector.routes.audio import (
    generate_edge_tts_audio as generate_edge_tts_audio,
)

# LLM 出网唯一收口（Task 3）：本模块 5 处重复的 httpx + /chat/completions 全部改调
# llm_client.chat。取**模块对象**而非 `from ... import chat`：monkeypatch 打在调用方
# 模块上才生效（本仓既有约定，见 tests 里对 `delector.routes.main.*` 的打桩）。
# 注意：本模块其余出网（TTS 兜底、fetch_remote_html）仍直接用 httpx，不在本次收口范围。
from delector.routes.backup import RestoreReq as RestoreReq
from delector.routes.cards import (
    GrammarCardReq as GrammarCardReq,
)
from delector.routes.cards import (
    VocabCardReq as VocabCardReq,
)
from delector.routes.cards import (
    add_grammar_card as add_grammar_card,
)
from delector.routes.cards import (
    calculate_fsrs as calculate_fsrs,
)
from delector.routes.cards import (
    calculate_sm2 as calculate_sm2,
)
from delector.routes.cards import (
    get_cards as get_cards,
)
from delector.routes.cards import (
    get_fsrs_next_intervals as get_fsrs_next_intervals,
)
from delector.routes.syntax_hard import invalidate_rank_cache
from delector.services import llm_client, polish_loop

# 统一违规抽取器（Task 1）：端点层与裁判层共用同一形状口径。取具名符号（纯函数，无循环依赖）。
from delector.services.writing import analyze_a1_email, collect_violations
from delector.tools.polish import POLISH_TOOL_ALLOWLIST, call_tool

router = APIRouter()


class IngestReq(BaseModel):
    title: Optional[str] = "Untitled"
    # 局域网可达 + spaCy 全文重算，必须有上限（防超大文本打满 NLP 与磁盘）
    raw_text: str = Field(..., max_length=100_000)


class WritingAnalyzeReq(BaseModel):
    text: str


class EssayCreateReq(BaseModel):
    title: str
    content: str


class EssayUpdateReq(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class WritingCardReq(BaseModel):
    essay_id: int
    sentence_id: int
    span_index: int


class AIPolishReq(BaseModel):
    text: str
    # 默认关 ⇒ 既有 JSON 行为与既有测试逐字不变（响应体只新增 converged 两字段）。
    # 打开后返回 SSE（逐轮进度 + 取消），见 `_polish_event_stream`。
    stream: bool = False


class WritingApplyReq(BaseModel):
    essay_id: int
    original_text: str
    corrected_text: str
    accepted_indices: List[int]


class EssayVersionCreateReq(BaseModel):
    message: Optional[str] = "手动保存"


class EssayRestoreReq(BaseModel):
    version_id: int


class GrammarLookupReq(BaseModel):
    sentence: str
    target_phrase: str


class IngestUrlReq(BaseModel):
    url: str
    title: Optional[str] = ""


@router.post("/api/articles/ingest-url")
async def ingest_from_url(req: IngestUrlReq) -> Dict[str, Any]:
    if not is_safe_public_url(req.url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")

    raw_html = await fetch_remote_html(req.url)
    title, body_text = clean_html_to_article(raw_html)
    if not body_text or len(body_text.strip()) < 30:
        raise HTTPException(400, "未能从该网页提取到有效的德语正文，请尝试直接复制粘贴")

    final_title = req.title.strip() if req.title else title
    art_id = await asyncio.to_thread(ingest_article, final_title, body_text, None, req.url)
    # 事务已在 ingest_article 内提交（db_conn 正常退出即 commit）⇒ 此处失效聚合榜缓存：
    # 放在事务提交之后，新文章下一次 source=all 立即可见，不等 300s TTL。
    invalidate_rank_cache()
    with db_conn() as conn:
        row = conn.execute("SELECT processed_json FROM articles WHERE id = ?", (art_id,)).fetchone()
        pj = json.loads(row["processed_json"]) if row else {}
    return {"article_id": art_id, "title": final_title, "char_count": len(body_text), "stats": pj.get("stats", {})}


@router.get("/api/feed/sources")
def get_feed_sources() -> Dict[str, Any]:
    return {"sources": PRESET_FEEDS}


@router.get("/api/feed/items")
async def get_feed_items(url: str) -> Dict[str, Any]:
    if not is_safe_public_url(url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")
    raw_xml = await fetch_remote_html(url)
    items = parse_rss_feed(raw_xml)
    return {"url": url, "count": len(items), "items": items}


@router.post("/api/articles/ingest")
def ingest(req: IngestReq) -> Dict[str, Any]:
    art_id = ingest_article(req.title or "Untitled", req.raw_text)
    # 同 ingest_from_url：ingest_article 返回即事务已提交 ⇒ 失效聚合榜缓存（不等 300s TTL）。
    invalidate_rank_cache()
    return {"article_id": art_id, "title": req.title}


ARTICLES_LIST_DEFAULT_LIMIT = 200


@router.get("/api/articles")
def list_articles(limit: int = ARTICLES_LIST_DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    # 只读列表路径：不再对 stats 缺失行做逐行 NLP 重算 + UPDATE（N+1 写副作用）。
    # 惰性迁移唯一保留在单篇 GET /api/articles/{id}。
    #
    # P1-6 列表成本与文章数解耦（前端契约不变：{id,title,created_at,char_count,stats}
    # 五字段原样，renderMiniBar(a.stats) 消费的形状一字不动）：
    # - 改前捞整列 processed_json（单篇 45–54KB）却只交付 ~200B 的 stats，且无 LIMIT；
    #   合成基准（tools/bench_articles_list.py，2000 行 × 36KB）：945ms，其中 Python
    #   json.loads 解析 136MB ⇒ ~90%。
    # - 改后只投影 stats_json 落库时同步写的小列（ingest/预置/惰性迁移三路径同步写），
    #   Python 解析字节量 136MB → 31KB；基准 9.5ms（99.6×）。
    # - COALESCE 兜底：stats_json 为 NULL 的行（旧库回填时 processed_json 损坏/缺 stats、
    #   或老备份还原进来的行）当场用 json_extract 从 blob 取——只有这些**少数**行付
    #   blob 读取成本；其余行走纯小列投影。
    limit = max(1, limit)
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, length(raw_text) as char_count, "
            "COALESCE(stats_json, CASE WHEN json_valid(processed_json) "
            "THEN json_extract(processed_json, '$.stats') END) AS stats_json "
            "FROM articles ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
        raw = r["stats_json"]
        if raw:
            try:
                stats = json.loads(raw)
                d["stats"] = stats if isinstance(stats, dict) else {}
            except Exception:
                # 与旧口径一致：stats 子 JSON 损坏 ⇒ 空 dict，绝不让异常流出列表。
                d["stats"] = {}
        else:
            d["stats"] = {}
        result.append(d)
    return result


# P1-8 惰性迁移 single-flight：per-article 的锁（重算 spaCy 全量 + UPDATE 是成本主体，
# 8 并发打开同一篇陈旧文章曾 = 8× CPU 与 8× 写放大）。
#
# 权衡（为什么 per-article 而不是全局锁）：全局锁会把"8 篇**不同**旧文并发首开"
# 也串行化——spaCy 计算 0.5~1.7s/篇，串行即 4~14s 墙钟，比并发重算慢得多；
# per-article 锁只让**同一篇**的并发互斥（恰好就是我们要挡的重复计算），不同篇照常并行。
#
# 字典清理策略：单用户规模下**不做清理**——每把 threading.Lock ~100B，条目数上限
# = 打开过的陈旧文章数（千级 ≈ 几百 KB），且文章删除后残留的锁无害（不会再被
# GET 命中，DELETE /api/articles/{id} 与 GET 无共享状态）。清理逻辑本身反而引入
# 「取锁与删锁竞态」的新风险（A 拿锁、B 等锁、A 完成删锁、C 又建新锁），不划算。
_MIGRATION_LOCKS: Dict[int, threading.Lock] = {}
_MIGRATION_LOCKS_GUARD = threading.Lock()


def _migration_lock(article_id: int) -> threading.Lock:
    """取 per-article 迁移锁（字典本身的并发由一把小锁护——只护 dict 读写，纳秒级）。"""
    with _MIGRATION_LOCKS_GUARD:
        lock = _MIGRATION_LOCKS.get(article_id)
        if lock is None:
            lock = threading.Lock()
            _MIGRATION_LOCKS[article_id] = lock
        return lock


def _needs_lazy_migration(pj: Any) -> bool:
    """惰性迁移判据（与写入端单一真相源对齐）：非 dict / 无 stats / 版本落后 ⇒ 需迁移。"""
    return not (isinstance(pj, dict) and "stats" in pj and pj.get("version") == PROCESSED_JSON_VERSION)


@router.get("/api/articles/{article_id}")
def get_article(article_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        data = dict(row)
        try:
            pj = json.loads(data.get("processed_json") or "{}")
        except Exception:
            pj = {}
        if _needs_lazy_migration(pj):
            # 惰性迁移：老数据（processed_json 缺失/非 dict/无 stats/版本落后）首次 GET
            # 时重算并回写。判据 MUST 引用 processor 的单一真相源 —— 曾硬编码字面量
            # 与写入端漂移，导致本分支恒真 ⇒ 每次 GET 都重跑 spaCy 并 UPDATE。
            #
            # P1-8 single-flight：拿 per-article 锁 + **锁内重检**——等锁期间别的请求
            # 可能已完成迁移并提交，重检命中 ⇒ 直接用现成结果，不重算不重写。
            # spaCy 计算留在事务内（既有语义）：UPDATE 仍在 db_conn 的事务里，
            # 异常整体回滚、无半写；锁只做"同篇互斥"，不改变事务边界。
            with _migration_lock(article_id):
                fresh = conn.execute(
                    "SELECT processed_json FROM articles WHERE id = ?", (article_id,)
                ).fetchone()
                try:
                    fresh_pj = json.loads(fresh["processed_json"]) if fresh is not None else None
                except Exception:
                    fresh_pj = None
                if not _needs_lazy_migration(fresh_pj):
                    pj = fresh_pj  # 别的请求已迁完：直接用，不重算（这正是省掉 7/8 CPU 的那一行）
                else:
                    pj = process_german_text(data.get("raw_text") or "")
                    conn.execute(
                        # P1-6：惰性迁移同步回写 stats 投影列（否则该行列表永远走 blob 兜底）。
                        # UPDATE 的事务边界不变：仍在 db_conn 的事务里，异常整体回滚、无半写。
                        "UPDATE articles SET processed_json = ?, stats_json = ? WHERE id = ?",
                        (
                            json.dumps(pj, ensure_ascii=False),
                            json.dumps(pj.get("stats") or {}, ensure_ascii=False),
                            article_id,
                        ),
                    )
                    # 提交必须在**释放锁之前**完成：重检读的是"已提交"数据，若 commit
                    # 留在 handler 末尾（锁外），等锁者拿锁重检时读到的仍是陈旧值 ⇒
                    # single-flight 空转（实测 8 并发算 2 次）。提前 commit 只改提交时机、
                    # 不改事务内容：仍只有这一条 UPDATE，异常时不走到这行、整体回滚。
                    conn.commit()
        data.update(pj)
        return data


@router.delete("/api/articles/{article_id}")
def delete_article(article_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        conn.execute("DELETE FROM reading_notes WHERE article_id = ?", (article_id,))
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    # return 移出 with：删除已提交（db_conn 正常退出即 commit）后才失效聚合榜缓存，
    # 已删文章下一次 source=all 立即消失，不滞留 300s TTL。404 早退路径不失效（无变更）。
    invalidate_rank_cache()
    return {"deleted": True, "article_id": article_id}


@router.post("/api/lookup/grammar")
async def lookup_grammar(req: GrammarLookupReq, request: Request) -> Any:
    # P1-5 本机闸：本端点有 key 时会真实出网烧 DeepSeek 配额，桌面端绑 0.0.0.0，
    # 不挂闸 ⇒ 同网段任意设备可无鉴权烧光配额。形态与模块内既有受保护端点
    # （delete_article / delete_card 等）一致：request 入参 + 函数体首行直调。
    _require_localhost(request)
    key = get_effective_api_key()
    if not key:
        return {
            "grammar_name": f"语法考点辨析 ({req.target_phrase})",
            "cefr_level": "A1",
            "explanation_zh": "请在右上角「⚙️ 设置」中配置 API Key 获取实时歌德大纲 AI 分析。",
            "rule_formula": "Grammar Pattern",
            "collocations": [f"{req.target_phrase} (常用释义)"],
        }

    base_url = get_effective_api_base_url().rstrip("/")
    model = get_effective_api_model()
    user_content = f'句子: "{req.sentence}"\n目标词/短语: "{req.target_phrase}"'
    try:
        return await llm_client.chat(
            [
                {"role": "system", "content": SYSTEM_GRAMMAR_PROMPT},
                {"role": "user", "content": user_content},
            ],
            model=model,
            max_tokens=llm_client.DEFAULT_MAX_TOKENS,
            timeout=30.0,  # 收口前本端点的现值（30s），语义不变
            response_format=llm_client.JSON_OBJECT,
            api_key=key,
            base_url=base_url,
        )
    except llm_client.LLMError as e:
        # 失败仍 502，detail 由 client 给出（与收口前逐字一致），此处不改写语义
        raise HTTPException(status_code=502, detail=e.detail)


SYSTEM_VOCAB_PROMPT = """你是一位精通德汉词典编纂的德语专家。
请根据给定的德语句子上下文和目标词汇，给出该词在当前句中的精准中文简明释义（1-8个字）、复数形式（如果是名词）、常用同义词等。
以严格的 JSON 格式输出：
{
  "definition_zh": "精准中文简明释义（如：挑战 / 减少 / 气温）",
  "plural": "复数形式（如：die Herausforderungen，若非名词留空）",
  "synonyms": ["同义词1", "同义词2"]
}
不要输出除 JSON 以外的任何文字。"""


class VocabLookupReq(BaseModel):
    sentence: str
    target_word: str
    lemma: Optional[str] = None  # 前端带上的 spaCy 词元（无 spaCy 时回退 None）


@router.post("/api/lookup/vocab")
async def lookup_vocab(req: VocabLookupReq, request: Request) -> Dict[str, Any]:
    # P1-5 本机闸：AI 兜底层（Tier 2）会出网烧配额，理由同 /api/lookup/grammar。
    _require_localhost(request)
    # 查词链重排：离线零延迟层在前，AI 垫底。原来只查表面形（token.text），
    # geht/Häuser/ist 全查不到；现在 lemma 优先（spaCy 入库时已算好 token.lemma）。
    res = {}

    # Tier 1: 核心词库（lemma 优先，表面形兜底）
    for word in (req.lemma, req.target_word):
        if not word:
            continue
        local_hit = lookup_core_vocab(word)
        if local_hit:
            res = {
                "definition_zh": local_hit.get("definition_zh", ""),
                "plural": local_hit.get("plural", ""),
                "gender": local_hit.get("gender"),
                "pos": local_hit.get("pos"),
                "cefr_level": local_hit.get("cefr_level"),
                "synonyms": [],
                "source": "local_dict",
            }
            break

    # Tier 1.5: 形态学扩展词库（LINGUISTICS_VOCAB_EXT，之前主链从不查）
    if not res:
        for word in (req.lemma, req.target_word):
            if not word:
                continue
            ext_hit = lookup_linguistics_ext(word)
            if ext_hit:
                res = {
                    "definition_zh": ext_hit.get("definition_zh", ""),
                    "plural": ext_hit.get("plural", ""),
                    "gender": ext_hit.get("gender"),
                    "pos": ext_hit.get("pos"),
                    "cefr_level": ext_hit.get("cefr_level"),
                    "synonyms": [],
                    "source": "linguistics_ext",
                }
                break

    # Tier 2: AI 兜底（仅当本地无释义且有 key）
    if not res.get("definition_zh"):
        key = get_effective_api_key()
        if not key:
            res = {"definition_zh": "", "plural": "", "synonyms": [], "source": "none"}
        else:
            base_url = get_effective_api_base_url().rstrip("/")
            model = get_effective_api_model()
            user_content = f'句子: "{req.sentence}"\n目标词汇: "{req.target_word}"'
            try:
                res = await llm_client.chat(
                    [
                        {"role": "system", "content": SYSTEM_VOCAB_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    model=model,
                    max_tokens=llm_client.DEFAULT_MAX_TOKENS,
                    timeout=15.0,  # 收口前本端点的现值（15s），语义不变
                    response_format=llm_client.JSON_OBJECT,
                    api_key=key,
                    base_url=base_url,
                )
                res["source"] = "ai"
            except llm_client.LLMError as e:
                # 现状语义：HTTP 层回了非 200 ⇒ ai_error；200 但正文解析失败 / 传输层异常
                # ⇒ ai_exception。两者在下游（三态表回填 linguistics）行为不同，不得合并。
                res = {
                    "definition_zh": "",
                    "plural": "",
                    "synonyms": [],
                    "source": "ai_error" if (e.status_code is not None and e.status_code != 200) else "ai_exception",
                }

    # Morphology & Linguistics Layer:
    # 1. Irregular / Strong verbs Stammformen（始终附；释义只在本地兜底没出时回填）
    stamm = lookup_irregular_verb(req.lemma or req.target_word)
    if stamm:
        inf = getattr(stamm, "infinitiv", None) or (stamm.get("infinitiv") if hasattr(stamm, "get") else "")
        praet = getattr(stamm, "praeteritum", None) or (stamm.get("praeteritum") if hasattr(stamm, "get") else "")
        p2 = getattr(stamm, "partizip2", None) or (stamm.get("partizip2") if hasattr(stamm, "get") else "")
        hilf = getattr(stamm, "hilfsverb", None) or (stamm.get("hilfsverb") if hasattr(stamm, "get") else "")
        stamm_def = getattr(stamm, "definition_zh", None) or (
            stamm.get("definition_zh") if hasattr(stamm, "get") else ""
        )

        res["stammformen"] = {"infinitiv": inf, "praeteritum": praet, "partizip2": p2, "hilfsverb": hilf}
        # 放宽回填：本地/在线都没出释义时，用三态表的释义兜底（不只 "none"）
        if not res.get("definition_zh") and stamm_def:
            res["definition_zh"] = stamm_def
            if res.get("source") in ("none", "ai_error", "ai_exception"):
                res["source"] = "linguistics"

    # 2. Komposita compound word decomposition
    target_clean = req.target_word.strip()
    if len(target_clean) >= 7:
        parts = split_komposita(target_clean)
        if len(parts) >= 2:
            res["komposita"] = []
            for p in parts:
                p_copy = dict(p)
                if "definition_zh" not in p_copy and "def_zh" in p_copy:
                    p_copy["definition_zh"] = p_copy["def_zh"]
                if "def_zh" not in p_copy and "definition_zh" in p_copy:
                    p_copy["def_zh"] = p_copy["definition_zh"]
                res["komposita"].append(p_copy)
            if not res.get("definition_zh"):
                sub_defs = [
                    p.get("definition_zh") or p.get("def_zh")
                    for p in parts
                    if (p.get("definition_zh") or p.get("def_zh"))
                ]
                if sub_defs:
                    res["definition_zh"] = " + ".join(str(d) for d in sub_defs)
                    if res.get("source") in ("none", "ai_error", "ai_exception"):
                        res["source"] = "linguistics"

    # 3. 固定介词搭配（Verben/Adjektive mit Präpositionen）
    # 挂在同一个响应里而不是新开端点：抽屉那几个 banner box 的渲染/拆除都假定
    # 数据来自同一个响应对象，新端点要在前端引入第二个异步状态与竞态处理。
    praep = lookup_prep_collocations(req.lemma or "") or lookup_prep_collocations(req.target_word)
    if praep:
        res["praepositionen"] = praep

    return res


# ── Präpositionen-Matrix ─────────────────────────────────────────────────────
_prep_matrix_response_cache = None


def get_prep_matrix_with_cefr() -> Dict[str, Any]:
    """矩阵响应构建 + CEFR 注入，进程级缓存。

    CEFR 在这一层而不是 linguistics.build_prep_matrix 里注入：
    get_cefr_level 是 server 的启发式（含长度 fallback），留在这层才能
    保证「展示标签」变化时不污染纯函数的守恒契约测试。
    组间顺序同理 —— 「常用者优先」是对用户可见面的要求，属呈现策略。
    """
    global _prep_matrix_response_cache
    if _prep_matrix_response_cache is None:
        groups: List[Dict[str, Any]] = []
        for praep, by_case in build_prep_matrix().items():
            entries_by_case = {
                kasus: [{**e, "cefr": get_cefr_level(e["lemma"])} for e in entries]
                for kasus, entries in by_case.items()
            }
            groups.append(
                {
                    "praeposition": praep,
                    "total": sum(len(v) for v in entries_by_case.values()),
                    "cases": entries_by_case,
                }
            )
        # 同总数时按介词字母序兜底，避免 dict 插入序泄漏成不稳定的呈现顺序
        groups.sort(key=lambda g: (-g["total"], g["praeposition"]))
        _prep_matrix_response_cache = {"groups": groups}
    return _prep_matrix_response_cache


@router.get("/api/prep/matrix")
def api_prep_matrix() -> Dict[str, Any]:
    return get_prep_matrix_with_cefr()


class PrepSavedReq(BaseModel):
    lemma: str
    praep: str
    kasus: str


@router.get("/api/prep/saved")
def api_prep_saved() -> Dict[str, Any]:
    """返回当前用户已入卡的搭配 key 列表。"""
    return {"keys": sorted(get_prep_saved())}


@router.post("/api/prep/saved")
def api_add_prep_saved(req: PrepSavedReq) -> Dict[str, Any]:
    """记录一条搭配已入卡。"""
    add_prep_saved(req.lemma, req.praep, req.kasus)
    return {"status": "ok"}


# --- Reading Notes & AI Assist Endpoints ---
class ReadingNoteReq(BaseModel):
    sentence_id: Optional[int] = None
    selected_text: str = Field(..., max_length=20_000)
    color: Optional[str] = "yellow"
    note_content: Optional[str] = Field(default="", max_length=20_000)


@router.get("/api/articles/{article_id}/notes")
def list_article_notes(article_id: int) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/api/articles/{article_id}/notes")
def create_article_note(article_id: int, req: ReadingNoteReq) -> Dict[str, Any]:
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reading_notes "
            "(article_id, sentence_id, selected_text, color, note_content) VALUES (?, ?, ?, ?, ?)",
            (article_id, req.sentence_id, req.selected_text, req.color or "yellow", req.note_content or ""),
        )
        return {"id": cur.lastrowid, "status": "ok"}


@router.delete("/api/notes/{note_id}")
def delete_article_note(note_id: int, request: Request) -> Dict[str, Any]:
    # 删除批注同本机写闸约定：与 delete_article / delete_card / delete_essay 一致，
    # 防局域网设备任意删用户精读批注。
    _require_localhost(request)
    with db_conn() as conn:
        conn.execute("DELETE FROM reading_notes WHERE id = ?", (note_id,))
        return {"status": "ok"}


SYSTEM_NOTE_PROMPT = """你是一位精通德语阅读与考点剖析的资深私教。
请根据学习者给出的德语句子和选中的文本，为学习者生成一份简洁精准的中文精读随笔备忘要点（包括句法结构简析、高频固定搭配及地道中文翻译）。
以严格的 JSON 格式输出：
{
  "summary_zh": "中文一句话精读解析",
  "key_points": ["核心要点1", "核心要点2"]
}
不要输出除 JSON 以外的任何文字。"""


class NoteAssistReq(BaseModel):
    sentence: str = Field(..., max_length=20_000)
    selected_text: str = Field(..., max_length=20_000)


@router.post("/api/ai/note-assist")
async def note_assist(req: NoteAssistReq, request: Request) -> Any:
    # P1-5 本机闸：有 key 时真实出网烧配额，理由同 /api/lookup/grammar。
    _require_localhost(request)
    key = get_effective_api_key()
    if not key:
        import logging

        logging.warning("[note-assist] API Key not set — returning stub response. Set in Settings.")
        return {
            "summary_zh": f"精读重点：{req.selected_text}",
            "key_points": ["请在右上角「⚙️ 设置」中配置 API Key 获取深度 AI 语法与搭配解析。"],
            "_stub": True,
        }

    base_url = get_effective_api_base_url().rstrip("/")
    model = get_effective_api_model()
    try:
        return await llm_client.chat(
            [
                {"role": "system", "content": SYSTEM_NOTE_PROMPT},
                # 截断后再送 LLM：与 writing/analyze 一致，控制请求成本
                {
                    "role": "user",
                    "content": (f'整句: "{req.sentence[:2000]}"\n划选部分: "{req.selected_text[:2000]}"'),
                },
            ],
            model=model,
            max_tokens=llm_client.DEFAULT_MAX_TOKENS,
            timeout=20.0,  # 收口前本端点的现值（20s），语义不变
            response_format=llm_client.JSON_OBJECT,
            api_key=key,
            base_url=base_url,
        )
    except llm_client.LLMError as e:
        # 失败仍 502，detail 由 client 给出（与收口前逐字一致），此处不改写语义
        raise HTTPException(status_code=502, detail=e.detail)


# --- Study Guide Export (Markdown) ---
@router.get("/api/articles/{article_id}/export-guide")
def export_study_guide(article_id: int) -> Any:
    with db_conn() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Article not found")
        notes = conn.execute(
            "SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)
        ).fetchall()
        vocab = conn.execute("SELECT * FROM vocab_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        grammar = conn.execute(
            "SELECT * FROM grammar_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)
        ).fetchall()

    md = [f"# {art['title']} — DeLector 精读讲义\n"]
    md.append(f"> 导出日期: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 字符数: {len(art['raw_text'])}\n")

    if notes:
        md.append("## 📝 精读随笔与重点批注\n")
        for n in notes:
            md.append(f"- **高亮原句**: *{n['selected_text']}*")
            if n["note_content"]:
                md.append(f"  - 💡 **随笔笔记**: {n['note_content']}")
        md.append("")

    if vocab:
        md.append("## 🗂️ 核心生词表\n")
        md.append("| 单词 | 原型 | 词性 | CEFR | 中文释义 | 原文语境 |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for v in vocab:
            md.append(
                f"| **{v['word']}** | {v['lemma']} | {v['pos']} | {v['cefr_level']} | "
                f"{v['definition_zh']} | *{v['sentence_context']}* |"
            )
        md.append("")

    if grammar:
        md.append("## 🎓 歌德考点深度解析\n")
        for g in grammar:
            md.append(f"### ✦ {g['grammar_name']} ({g['cefr_level']})")
            if g["rule_formula"]:
                md.append(f"- **语法公式**: `{g['rule_formula']}`")
            md.append(f"- **解析**: {g['explanation_zh']}")
            md.append(f"- **例句**: *{g['sentence_context']}*\n")

    content = "\n".join(md)
    from fastapi.responses import Response

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers=_attachment_headers(f"study_guide_{article_id}.md"),
    )


def generate_cloze_exercise(text: str, mode: str = "grammar", article_id: Optional[int] = None) -> Dict[str, Any]:
    if nlp is None:
        # Simple pure-Python cloze fallback
        words = re.findall(r"\w+|[^\w\s]+|\s+", text, re.UNICODE)
        items = []
        tokens_output = []
        blank_counter = 0
        for w in words:
            if w.isalpha() and len(w) >= 4 and blank_counter < 5 and blank_counter % 2 == 0:
                first_letter = w[0]
                items.append(
                    {
                        "index": blank_counter,
                        "original": w,
                        "first_letter": first_letter,
                        "lemma": w.lower(),
                        "pos": "NOUN" if w[0].isupper() else "VERB",
                        "hint": f"首字母: {first_letter}...",
                        "type": mode,
                        "sent_idx": 0,
                    }
                )
                tokens_output.append(f"[[BLANK_{blank_counter}]]")
                blank_counter += 1
            else:
                tokens_output.append(w)
        return {
            "version": "3.5.0",
            "mode": mode,
            "article_id": article_id,
            "masked_text": "".join(tokens_output),
            "blanks_count": len(items),
            "items": items,
        }
    doc = nlp(text)
    items = []
    tokens_output = []
    blank_counter = 0

    if mode == "grammar":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                is_grammar_target = (
                    token.pos_ in ("ADP", "SCONJ", "CCONJ")
                    or (
                        token.pos_ == "AUX"
                        and token.text.lower()
                        in ("wurde", "worden", "werden", "wäre", "hätte", "könnte", "müsste", "sollte")
                    )
                    or (token.pos_ == "ADJ" and len(token.text) > 3)
                )
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_grammar_target and len(sent_blanks) < 2 and len(token.text) >= 2:
                    first_letter = token.text[0]
                    items.append(
                        {
                            "index": blank_counter,
                            "original": token.text,
                            "first_letter": first_letter,
                            "lemma": token.lemma_,
                            "pos": token.pos_,
                            "hint": f"首字母: {first_letter}...",
                            "type": "grammar",
                            "sent_idx": sent_idx,
                        }
                    )
                    tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                    blank_counter += 1
                else:
                    tokens_output.append(token.text_with_ws)

    elif mode == "vocab":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                lvl = get_cefr_level(token.lemma_)
                is_vocab_target = (
                    token.pos_ in ("NOUN", "VERB") and lvl in ("A2", "B1", "B2", "C1") and len(token.text) >= 3
                )
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_vocab_target and len(sent_blanks) < 2:
                    first_letter = token.text[0]
                    items.append(
                        {
                            "index": blank_counter,
                            "original": token.text,
                            "first_letter": first_letter,
                            "lemma": token.lemma_,
                            "pos": token.pos_,
                            "hint": f"首字母: {first_letter}... ({token.lemma_})",
                            "type": "vocab",
                            "sent_idx": sent_idx,
                        }
                    )
                    tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                    blank_counter += 1
                else:
                    tokens_output.append(token.text_with_ws)

    elif mode == "ctest":
        for sent_idx, sent in enumerate(doc.sents):
            word_in_sent_idx = 0
            for token in sent:
                if token.is_alpha and len(token.text) >= 3:
                    word_in_sent_idx += 1
                    if sent_idx >= 1 and word_in_sent_idx % 2 == 0:
                        cut_len = (len(token.text) + 1) // 2
                        prefix = token.text[:cut_len]
                        suffix = token.text[cut_len:]
                        items.append(
                            {
                                "index": blank_counter,
                                "original": token.text,
                                "prefix": prefix,
                                "suffix": suffix,
                                "first_letter": prefix,
                                "hint": f"词首: {prefix}...",
                                "type": "ctest",
                                "sent_idx": sent_idx,
                            }
                        )
                        tokens_output.append(f"{prefix}[[BLANK_{blank_counter}]]{token.whitespace_}")
                        blank_counter += 1
                        continue
                tokens_output.append(token.text_with_ws)

    if len(items) == 0:
        for token in doc:
            if token.is_alpha and len(token.text) >= 4 and blank_counter < 3:
                first_letter = token.text[0]
                items.append(
                    {
                        "index": blank_counter,
                        "original": token.text,
                        "first_letter": first_letter,
                        "lemma": token.lemma_,
                        "hint": f"首字母: {first_letter}...",
                        "type": mode,
                        "sent_idx": 0,
                    }
                )
                tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                blank_counter += 1
            else:
                tokens_output.append(token.text_with_ws)

    masked_text = "".join(tokens_output)
    return {"mode": mode, "items": items, "total_blanks": len(items), "masked_text": masked_text}


class ClozeGenReq(BaseModel):
    mode: Optional[str] = "grammar"


@router.post("/api/articles/{article_id}/exercise/cloze")
def get_article_cloze_exercise(article_id: int, req: ClozeGenReq) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Article {article_id} not found")
        raw_text = row["raw_text"]
        title = row["title"]

    data = generate_cloze_exercise(raw_text, mode=req.mode or "grammar", article_id=article_id)
    data["article_id"] = article_id
    data["title"] = title
    return data


class ClozeEvalReq(BaseModel):
    article_id: int
    mode: str
    answers: Dict[str, str]


@router.post("/api/exercise/cloze/evaluate")
def evaluate_cloze_exercise(req: ClozeEvalReq) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (req.article_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Article {req.article_id} not found")
        raw_text = row["raw_text"]

    exercise = generate_cloze_exercise(raw_text, mode=req.mode, article_id=req.article_id)
    items = exercise["items"]

    results = []
    correct_count = 0
    for item in items:
        idx_str = str(item["index"])
        user_ans = req.answers.get(idx_str, "").strip()
        expected = item["original"]

        if item.get("type") == "ctest":
            expected_suffix = item.get("suffix", "")
            is_correct = (user_ans.lower() == expected_suffix.lower()) or (user_ans.lower() == expected.lower())
        else:
            is_correct = user_ans.lower() == expected.lower()

        if is_correct:
            correct_count += 1

        results.append(
            {
                "index": item["index"],
                "correct": is_correct,
                "user_answer": user_ans,
                "expected": expected,
                "hint": item.get("hint", ""),
                "type": item.get("type", "grammar"),
            }
        )

    total = len(items)
    accuracy_pct = round((correct_count / total * 100)) if total > 0 else 0

    log_study_event("quiz_session", req.article_id, f"cloze:{req.mode}:{req.article_id}", minutes=3)

    return {"score": correct_count, "total": total, "accuracy_pct": accuracy_pct, "results": results}


class SyntaxAnalyzeReq(BaseModel):
    text: str


@router.post("/api/syntax/analyze")
def api_syntax_analyze(req: SyntaxAnalyzeReq) -> Any:
    return analyze_syntax_tree(req.text)


# --- Writing Desk (Schreibwerkstatt) Endpoints ---

# ── AI 润色：有界循环（Task 6）——适用性闸门 / 录制包装 / SSE ─────────────────
# 端点层原因码：循环**根本没跑**（无 API Key），不是循环的任何一种结局 ⇒ **不进**
# `polish_loop.REASONS`（加进去会让「原因码集合 = 循环的出口」这条契约失真）。
REASON_NO_API_KEY = "no_api_key"

# SSE 的断连探活间隔。`request.is_disconnected()` 在 starlette 1.6 是**非阻塞**的
# （内部用一个已取消的 anyio CancelScope 包住 receive()：没有排队消息就立刻返回 False），
# 所以可以在生成器的每一圈安全轮询，不会挂住流。
_SSE_POLL_INTERVAL_S = 0.02


# 格式/字数族 = 书信题材专属规则的 rule 前缀（`a1_*`：称呼语 / 结语 / 字数）。
# 语法族 = 不以 `a1_` 开头的 rule（artikel / kasus / praeposition / numerus / rektion /
# wortstellung）—— **与题材无关** ⇒ 对任意德语文本生效（Task 7 收窄；`tempus` 是 advisory、
# 不进 `collect_violations` 的输出，天然不参与计数）。
_LETTER_FORMAT_RULE_PREFIX = "a1_"


def _text_kind(verdict: Dict[str, Any]) -> str:
    """文本族判定：**沿用既有 `greeting.valid` 口径**（书信体 ⇔ 称呼语合法）。

    ⚠️ 以 `greeting.valid` 为唯一判据的三条边界后果（**如实登记，勿删**）：

    ① **书信缺称呼语** ⇒ 归 `prose` ⇒ 格式族（含 `a1_greeting_missing` 这条 error）被
       `a1_` 前缀过滤 ⇒ 该类邮件的格式错**永远不被计数**；且提示词按初始文本族装配
       （`pick_system_prompt`）⇒ 走散文版。这是**继承自旧闸门**的边界，不是本批回归。
    ② **散文含称呼语** ⇒ 归 `letter` ⇒ 格式族照用（对散文生效）+ 书信版提示词。
    ③ **候选侧翻转（未收口欠账）**：循环的 kind **逐候选**按候选自身裁决体判定
       （`_polish_violations_of` 单参契约）⇒ 模型"删掉称呼语"的那个候选会翻转口径 ——
       该候选自身的格式族违规被过滤后 v 可能掉到 0。这是 2026-10-14 计划里已登记的
       "闸门对候选单向生效"欠账，本批**未收口**，如实登记。
    """
    greeting = verdict.get("greeting") if isinstance(verdict, dict) else None
    if isinstance(greeting, dict) and greeting.get("valid"):
        return "letter"
    return "prose"


def violations_for(kind: str, verdict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """适用性闸门（**Task 7 收窄版**：按**规则族**分流，而不是按整份裁判开关）。

    - `kind == "letter"` ⇒ 格式/字数族（`a1_*`）+ 语法族 **全计**；
    - `kind == "prose"` ⇒ **只计语法族**（语法与题材无关）—— 这就是「循环的价值面扩到
      任意德语文本」的落点。

    统一抽取器：走 `collect_violations`（新键 `violations` 优先、legacy `suggestions` 回退，
    且只取 `level == "error"`），与裁判层同口径；advisory（warning 级）不在其输出里。

    ⚠️ **产品语义（ADR §10.3 失败模式的实际落点，MUST NOT 静默改）**：非书信文本的语法违规
    开始计数 ⇒ 若模型修不动（v 不降），循环按 Task 4 钉死的语义走 `no_improvement` ⇒ argmin
    回退**原文**（**不是**"首轮即接受"）。这是**明知而接受**的行为变更（2026-10-15 用户拍板）：
    价值面从"仅 A1 书信"扩到"任意德语文本"，代价是修不动的文本拿到原文 + 人话原因码
    （前端 `POLISH_REASON_COPY.no_improvement`）。

    历史注记（为什么不再"非书信体一律零违规"）：旧闸门是针对"裁判只有书信格式规则"的权宜
    —— 当时 `a1_greeting_missing` 对每篇非书信文本恒报 error ⇒ v 恒 > 0 ⇒ 恒回退原文。
    语法维度接线后前提变了：上面的失败模式只在**模型真修不动**时出现，而不是对非书信文本恒真。
    """
    violations = collect_violations(verdict)
    if kind == "letter":
        return violations
    return [v for v in violations if not str(v.get("rule", "")).startswith(_LETTER_FORMAT_RULE_PREFIX)]


def _polish_violations_of(verdict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """循环入口（单参，`violations_of` 契约）：文本族由**裁决体自己**判（沿用 `greeting.valid`）。"""
    return violations_for(_text_kind(verdict), verdict)


# 散文向系统提示词（Task 7 的立论冲突解法 b：提示词按**文本族**参数化，业务知识住产品层）。
# 与书信版（内核 `polish_loop.POLISH_LOOP_SYSTEM_PROMPT`）的差异——**只删题材指令，不动协议**：
# - 去掉逐字的 A1 书信自查指令（"称呼语存在且以逗号结尾 / 逗号后正文首词小写 / 结语后不得加
#   逗号"）：评审黄卡 #2 —— 对非书信文本它会**诱导模型加一个称呼语**，而格式族规则此时已被
#   闸门关掉 ⇒ 污染无守卫；
# - **保留** JSON 契约（循环按它解析回复）与"逐句润色、保持句子结构与出现顺序"（来自
#   `essay_diff.diff_sentences` 的按句对齐，diff 逐 hunk 采纳 UI 的**关键约束**）。
POLISH_PROSE_SYSTEM_PROMPT = (
    "你是德语写作润色助手。每一轮**只**回复一个 JSON 对象，不要输出任何其他文字。\n"
    "回复有且只有两种形态：\n"
    '1) 还需要证据：{"tool_call": {"name": "<工具名>", "payload": {...}}}\n'
    '2) 可以收尾：{"corrected_text": "<润色后的全文>", "notes_zh": ["<中文说明>", ...]}\n'
    "工具名必须在可用工具列表里，否则会被拒绝并把错误原样回传给你。\n"
    "请尽量逐句润色，保持句子的结构与出现顺序，不要合并或拆分句子，除非确实必要。"
)


def pick_system_prompt(kind: str) -> str:
    """文本族 → 系统提示词（Task 7；**业务知识住在产品层**，内核只收参数）。

    - `"letter"` ⇒ 既有 A1 书信提示词（`polish_loop.POLISH_LOOP_SYSTEM_PROMPT`，逐字）；
    - 其余（`"prose"` 及未知值）⇒ 散文向提示词 —— 未知 kind 取散文向是**保守默认**：
      宁少一条题材指令（漏掉书信自查），也不冒"对非书信文本诱导加称呼语"的污染风险。
    """
    if kind == "letter":
        return polish_loop.POLISH_LOOP_SYSTEM_PROMPT
    return POLISH_PROSE_SYSTEM_PROMPT


def _make_tool_audit_hook(seen: List[str]) -> Any:
    """润色工具的前置钩子：**权限闸 + 审计留痕**（Task 5 的 hooks 面，每次请求新建）。

    权限闸在这里再挡一次白名单（纵深防御）：`call_tool` 内部已有同名兜底，但钩子
    是「调用之前」的唯一挂点，把「能力面」检查放在这里才不会被 dispatcher 的实现
    细节带着走。钩子抛异常 ⇒ 该次调用被拒（errors-as-messages，不炸循环）。
    """

    def _audit(name: str, _payload: Dict[str, Any]) -> None:
        if name not in POLISH_TOOL_ALLOWLIST:
            raise PermissionError(f"工具 '{name}' 不在润色白名单内")
        seen.append(name)

    return _audit


class _PolishReplyRecorder:
    """`llm_client.chat` 的**录制包装**：从每一轮回复里捕获最后的 `notes_zh` /
    `error_count`，再原样返回。

    为什么端点要自己录、而不是直接用 `LoopResult` 的字段：`error_count` 今天的语义是
    **模型报的数**（`tests/test_server.py::test_ai_polish_diff_mocked` 的
    `error_count == 2` 就来自模型回复）。改成裁判口径会**静默破坏既有断言**，故原样
    记录：模型给了就用模型的；没给回退 `len(notes_zh)`；再没有才回退 `len(violations)`。

    本包装**不碰文本归属**：收敛 ⇒ 返回那个零违规候选；未收敛 ⇒ argmin 回退，这个
    结论由循环自己给出（`polish_loop.run_polish_loop` 出口）。端点曾按
    `last_corrected_text` 兜底，但 recorder 分不清「收尾候选轮」与「取证轮」——
    模型在取证轮回个 `corrected_text`（协议外字段）就会被误当成采纳文本，故删掉。

    `model` 由本包装自己取真身：循环在**注入 chat** 时不读配置（测试不该碰数据库），
    传进来的 `model` 是空串。
    """

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self.notes_zh: List[str] = []
        self.error_count: Optional[int] = None
        self.usage: Optional[Dict[str, int]] = None

    async def __call__(
        self,
        *,
        messages: List[Dict[str, Any]],
        model: str,
        timeout: float,
        max_tokens: int,
        response_format: Optional[Dict[str, str]] = None,
        **_kwargs: Any,
    ) -> Dict[str, Any]:
        reply = await llm_client.chat(
            messages=messages,
            model=get_effective_api_model(),
            timeout=timeout,
            max_tokens=max_tokens,
            response_format=response_format,
            include_usage=True,
            api_key=self._api_key,
            base_url=self._base_url,
        )
        self._capture(reply)
        return reply

    def _capture(self, reply: Any) -> None:
        if not isinstance(reply, dict):
            return
        notes = reply.get("notes_zh")
        if isinstance(notes, list):
            self.notes_zh = [str(item) for item in notes]
        count = reply.get("error_count")
        if isinstance(count, int) and not isinstance(count, bool):
            self.error_count = count
        usage = reply.get("usage")
        if isinstance(usage, dict):
            self.usage = {
                str(k): int(v)
                for k, v in usage.items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)
            }


def _make_judge(leitpunkte: Optional[List[str]], nlp: Any) -> Callable[[str], Dict[str, Any]]:
    """装配生产链路用的 **A1 裁判**（带 nlp）：内部调 `analyze_a1_email(text, leitpunkte, nlp)`。

    为什么必须由**产品层**装配、而不能用内核默认裁判：内核默认裁判是
    `polish_loop._default_judge` = `analyze_a1_email(text, leitpunkte)`（**不带 nlp**）⇒ 语法族
    恒不生效。能力必须在产品层装配，内核只保留「谁都能被注入」的缝（评审 RED#1 的闭环点）。

    降级语义边界（如实登记，勿删）：`nlp is None` 时本裁判只跑格式族、`judge_engine="rules_only"`；
    此时循环**照常收敛**（运行期 fail-open —— 禁止收敛会让 argmin 回退返回原文 = 功能报废）。
    “没检查语法”不等于“语法零违规”：声明层的诚实性由裁决体的 `judge_engine` 透出
    （`_JudgeRecorder` 捕获 → 响应体 `judge_degraded`），门禁层 fail-closed 由调用方承担。
    **禁止**靠塞一条人造 violation 来实现降级提示。

    ⚠️ **非书信文本的产品语义（Task 7 收窄后的落点；ADR §10.3 失败模式的实际发生点，勿删）**：
    本裁判对**任意德语文本**都会给出语法族裁决（语法与题材无关），闸门（`violations_for`）只把
    格式/字数族（`a1_*`）限给书信体。后果：非书信文本 + 语法错若**模型修不动**（候选的 v 不降），
    循环按 Task 4 钉死的语义走 `no_improvement` ⇒ argmin 回退**原文** ——
    **不是**"首轮即接受"，用户拿到原文 + 前端人话原因码（`no_improvement`）。
    这是 2026-10-15 用户拍板的**明知而接受**的行为（价值面从"仅 A1 书信"扩到"任意德语文本"）。
    """

    def _judge(text: str) -> Dict[str, Any]:
        return analyze_a1_email(text, leitpunkte, nlp)

    return _judge


class _JudgeRecorder:
    """裁判的**录制包装**（与 `_PolishReplyRecorder` 同形）：记下每次裁决的 `judge_engine`
    与 `judge_advisories`，再原样返回裁决。

    为什么端点要自己录：`judge_engine` / `advisories` 住在裁决体里（`analyze_a1_email` 的
    并列字段），而循环出口的 `LoopResult` 不带它们 ⇒ 端点必须从裁判这一侧捕获，才能把
    降级状态与 advisory **如实透出**到响应体（红线 1：不得让“没检查”看起来像“检查通过”；
    Task 6 HITL：warning 必须真能被看到，否则是 no-op）。

    `judge_advisories` 取裁决体 `advisories`（统一形状、`level=="warning"`）的 `message`
    文本；它**不进** `violations`（`violations_of`/`collect_violations` 只认 `level=="error"`）
    ⇒ 不改变 v、不阻断收敛。每次裁决**覆盖式**记录：记录的是**最后一次裁决**。

    ⚠️ 收窄说明（如实登记，勿删）：**argmin 回退路径下 `judge_advisories` 可能与出口文本
    不一致** —— 未收敛时循环出口走 `min(history, key=v)` 回退，出口文本可能是**更早**的
    候选或原文（`min` 并列取最早 ⇒ 此时原文胜出），而本包装记的是**最后一次裁判调用**的
    裁决 ⇒ 响应体 advisory 描述的是"最后一次被裁的文本"，不保证是返回给用户的那份。
    非阻断：advisory **不进任何计数**（v / 停止策略 / 收敛归属全不受它影响）⇒ 仅呈现层
    的对应性欠账。（`judge_engine` 是引擎装配态、与文本无关，不受此影响。）

    `__call__` 的第二参数兼容循环的 `judge_fn(text, leitpunkte)` 调用约定（leitpunkte 已由
    `_make_judge` 闭包绑定，这里忽略即可）。
    """

    def __init__(self, judge_fn: Callable[[str], Dict[str, Any]]) -> None:
        self._judge_fn = judge_fn
        # 未被裁过时的保守默认：宁报降级（rules_only）不报可用，避免“没跑却标成已跑”。
        self.judge_engine: str = "rules_only"
        self.judge_advisories: List[str] = []

    def __call__(self, text: str, leitpunkte: Optional[List[str]] = None) -> Dict[str, Any]:
        verdict = self._judge_fn(text)
        if isinstance(verdict, dict):
            engine = verdict.get("judge_engine")
            if isinstance(engine, str) and engine:
                self.judge_engine = engine
            advisories = verdict.get("advisories")
            if isinstance(advisories, list):
                self.judge_advisories = [str(a.get("message", "")) for a in advisories if isinstance(a, dict)]
        return verdict


class _PolishOutcome(NamedTuple):
    """一次润色的出口（端点据此组装响应体，流式与非流式共用一份）。

    `judge_engine`（追加，Task 1）：本次运行实际装配的裁判引擎（`"rules+spacy"` / `"rules_only"`），
    端据此算出响应体 `judge_degraded`。

    `judge_advisories`（追加，Task 6 HITL 收尾）：最后一次裁决的 advisory 文本（warning 级，
    当前 = B 维 `tempus`）——响应体 `judge_advisories` 的承载，**不参与任何计数**。
    """

    text: str
    notes_zh: List[str]
    error_count: int
    converged: bool
    reason: Optional[str]
    judge_engine: str
    judge_advisories: List[str]


def _no_key_outcome(text: str) -> _PolishOutcome:
    """无 API Key：**不走循环**，今日语义逐字保留（文本原样 + 提示去配 Key）。"""
    import logging

    logging.warning("[writing/ai-polish] API Key not set — returning stub response.")
    return _PolishOutcome(
        text=text,
        notes_zh=["请在设置中配置 DeepSeek API Key 后使用 AI 润色功能"],
        error_count=0,
        converged=False,
        reason=REASON_NO_API_KEY,
        # 循环没跑 ⇒ 裁判也未装配 ⇒ 保守记为降级（宁报降级不报可用）。
        judge_engine="rules_only",
        judge_advisories=[],
    )


async def _run_polish(
    text: str,
    api_key: str,
    *,
    on_progress: Optional[Any] = None,
    should_stop: Optional[Any] = None,
) -> _PolishOutcome:
    """跑一遍润色循环：Task 4 内核 + Task 5 白名单/钩子 + **规则族闸门** + 语法裁判装配 +
    **文本族感知的提示词装配**。

    引擎来源（评审 RED#1 的闭环点）：先**只读**已加载模型（`get_loaded_nlp`，不触发加载/下载）；
    没有则在线程里尝试**仅本地**加载（`try_load_nlp_no_download` 绝不 `spacy.cli.download`，
    且同步函数放 `asyncio.to_thread` 里跑，不阻塞事件循环）。`nlp=None` ⇒ 裁判降级为
    `rules_only`、循环照常收敛，降级状态由 `judge_engine` 如实透出（响应体 `judge_degraded`）。

    文本族（Task 7）：`kind` 由**纯规则**裁决体判一次（见下方注释），决定
    ①系统提示词（`pick_system_prompt`：内核的 A1 书信指令对非书信体不适用）；
    ②闸门口径（`violations_for`：格式族只对书信体、语法族对任意德语文本）。

    产品语义（ADR §10.3 的落点，同款登记在 `violations_for` / `_make_judge` docstring）：
    非书信文本的语法违规**会计数** ⇒ 模型修不动时 `no_improvement` ⇒ argmin 回退**原文**
    （**不是**"首轮即接受"）。
    """
    import logging

    seen: List[str] = []
    recorder = _PolishReplyRecorder(api_key, get_effective_api_base_url().rstrip("/"))
    # 引擎解析：先只读 → 再线程内本地加载（无下载）。绝不阻塞事件循环、绝不触发出网。
    nlp = _nlp_processor.get_loaded_nlp()
    if nlp is None:
        nlp = await asyncio.to_thread(_nlp_processor.try_load_nlp_no_download)
    # 文本族（选提示词用）：纯规则口径（不传 nlp ⇒ 不加载、不跑 spaCy）；`greeting.valid`
    # 本身是纯规则，与带 nlp 的裁决逐字一致。只用于装配提示词，不当作裁决（裁决仍由
    # judge_recorder 全量记录并透出）。
    kind = _text_kind(analyze_a1_email(text))
    judge_recorder = _JudgeRecorder(_make_judge(None, nlp))
    try:
        loop = await polish_loop.run_polish_loop(
            text=text,
            tools=POLISH_TOOL_ALLOWLIST,
            dispatch=functools.partial(call_tool, hooks=(_make_tool_audit_hook(seen),)),
            violations_of=_polish_violations_of,
            system_prompt=pick_system_prompt(kind),
            # 必须真的注入（不能退回内核默认裁判）—— 否则生产上语法裁判恒不生效 = dead-green。
            judge=judge_recorder,
            chat=recorder,
            budget=polish_loop.Budget(),
            text_type=kind,
            on_progress=on_progress,
            should_stop=should_stop,
        )
    except llm_client.LLMError as e:
        logging.error(f"[writing/ai-polish] DeepSeek API error: {e.detail} | raw: {e.raw[:200]}")
        raise HTTPException(status_code=502, detail=e.detail)
    if seen:
        logging.info("[writing/ai-polish] 工具调用: %s", ", ".join(seen))
    # 文本归属由循环自己给（Task 6 修订）：收敛 ⇒ 返回那个被判为零违规的候选；
    # 未收敛 ⇒ argmin 回退（Task 4 钉死的语义，`no_improvement` 回退原文是特性）。
    # 端点不再兜底：recorder 分不清「收尾候选轮」与「取证轮」，按 `corrected_text`
    # 兜底会把模型没被采用的文本当答案返回。
    final_text = loop.text
    error_count = recorder.error_count
    if error_count is None:
        error_count = len(recorder.notes_zh) if recorder.notes_zh else len(loop.violations)
    return _PolishOutcome(
        text=final_text,
        notes_zh=recorder.notes_zh,
        error_count=error_count,
        converged=loop.converged,
        reason=loop.reason,
        judge_engine=judge_recorder.judge_engine,
        judge_advisories=judge_recorder.judge_advisories,
    )


def _judge_degraded(outcome: _PolishOutcome) -> bool:
    """引擎降级标记（只增不改的响应字段）：`judge_engine != "rules+spacy"` ⇒ 语法族未启用。"""
    return outcome.judge_engine != "rules+spacy"


def _polish_payload(outcome: _PolishOutcome) -> Dict[str, Any]:
    """`/api/writing/ai-polish` 的 `result`（**只增不改**：追加 `judge_degraded` / `judge_advisories`）。"""
    return {
        "corrected_text": outcome.text,
        "notes_zh": outcome.notes_zh,
        "error_count": outcome.error_count,
        "converged": outcome.converged,
        "unconverged_reason": None if outcome.converged else outcome.reason,
        "judge_degraded": _judge_degraded(outcome),
        "judge_advisories": outcome.judge_advisories,
    }


def _polish_diff_payload(text: str, outcome: _PolishOutcome) -> Dict[str, Any]:
    """`/api/writing/ai-polish/diff` 的 `result`（既有字段与顺序一律不动，末尾追加 `judge_degraded` /
    `judge_advisories`）。"""
    from delector.services.essay_diff import diff_sentences

    return {
        "original": text,
        "corrected": outcome.text,
        "hunks": diff_sentences(text, outcome.text),
        "notes_zh": outcome.notes_zh,
        "error_count": outcome.error_count,
        "converged": outcome.converged,
        "unconverged_reason": None if outcome.converged else outcome.reason,
        "judge_degraded": _judge_degraded(outcome),
        "judge_advisories": outcome.judge_advisories,
    }


def _sse_frame(event: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


async def _polish_event_stream(*, request: Request, text: str, with_diff: bool) -> AsyncIterator[bytes]:
    """SSE：把循环的 `on_progress` 事件逐条吐出，最后一条是完整 `result`。

    取消：循环内每一圈探活，客户端已断开 ⇒ 置停止位（让循环自己收口）+ `task.cancel()`
    （掐断在途的那一次 chat，不再继续烧配额）后结束流。但这条轮询**赢不了**
    starlette 的 `listen_for_disconnect`（uvicorn HTTP scope spec_version='2.3' ⇒
    `StreamingResponse.__call__` 同时跑流与监听器，客户端断开时监听器抢先 cancel
    生成器）⇒ 外层再用 `try/finally` 兜底同步收尸，无论谁取消生成器在途 chat 都被掐断。
    """
    key = get_effective_api_key()
    if not key:
        # 无 Key 也走 SSE 形状（客户端只解析一种帧格式）：循环没跑，直接给 stub。
        outcome = _no_key_outcome(text)
        payload = _polish_diff_payload(text, outcome) if with_diff else _polish_payload(outcome)
        yield _sse_frame({"event": "result", "result": payload})
        return

    events: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    state = {"stop": False}

    async def _runner() -> _PolishOutcome:
        return await _run_polish(text, key, on_progress=events.put_nowait, should_stop=lambda: state["stop"])

    task = asyncio.ensure_future(_runner())
    try:
        while True:
            if await request.is_disconnected():
                state["stop"] = True
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return
            try:
                event = events.get_nowait()
            except asyncio.QueueEmpty:
                if task.done():
                    break
                await asyncio.sleep(_SSE_POLL_INTERVAL_S)
                continue
            yield _sse_frame(event)
            if event.get("event") == "done":
                break

        try:
            outcome = await task
        except HTTPException as e:
            # 流已经开了头（状态行已发出），改不了状态码 ⇒ 用一条 error 帧交代人话。
            #
            # 为什么捕 `HTTPException` 而不是 `llm_client.LLMError`（接缝③）：
            # `_run_polish` 早就把 `LLMError` 转成 `HTTPException(502, detail=e.detail)`，
            # 这里写 `except llm_client.LLMError` **永不命中** ⇒ 异常裸抛到
            # StreamingResponse 外层 ⇒ starlette 抛
            # "Caught handled exception, but response already started" ⇒ 用户既拿不到
            # 状态码也拿不到 error 帧，只剩前端那句通用文案。
            # 选 (b) 而不是 (a)（让 `_run_polish` 在流式路径原样抛 LLMError）的理由：
            # `_run_polish` 的失败契约对两种调用方 MUST 同一形状（都是 502 + 人话
            # detail），不该随「谁调它」变形；且流已开头、状态码改不了，error 帧是
            # 唯一能把 `e.detail` 送到用户面前的通道（前端 writer.js 已按
            # `ev.event === 'error'` / `ev.detail` 消费）。
            yield _sse_frame({"event": "error", "detail": e.detail})
            return
        payload = _polish_diff_payload(text, outcome) if with_diff else _polish_payload(outcome)
        yield _sse_frame({"event": "result", "result": payload})
    finally:
        # 收尸：无论谁取消生成器都必须掐断在途 chat，否则 task（ensure_future 的独立
        # Task）裸跑到自然结束会继续烧配额。取消来源有三：
        # 1) starlette 的 `listen_for_disconnect` 抢跑 —— uvicorn HTTP scope 的
        #    spec_version='2.3' ⇒ `StreamingResponse.__call__` 同时跑 stream_response
        #    与监听器；客户端一断开，监听器抢先 cancel 生成器，上面「先 await
        #    request.is_disconnected() 再 cancel」的轮询几乎永远输给它；
        # 2) 服务器主动取消（响应体消费方提前收手）；
        # 3) 循环自己 break/return 的正常收尾。
        # 只做**同步**收尸（state + cancel，不 await）：取消态里再 await 会被再次
        # 投递 CancelledError；确需 await 时放在同步 cancel 之后并用
        # `contextlib.suppress(asyncio.CancelledError)` 包住（见上方 is_disconnected 分支）。
        state["stop"] = True
        task.cancel()


@router.post("/api/writing/ai-polish")
async def api_writing_ai_polish(req: AIPolishReq, request: Request) -> Any:
    # P1-5 本机闸：循环有 key 时真实出网烧配额，理由同 /api/lookup/grammar。
    _require_localhost(request)
    text = req.text[:2000]
    if req.stream:
        return StreamingResponse(
            _polish_event_stream(request=request, text=text, with_diff=False),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    key = get_effective_api_key()
    outcome = _no_key_outcome(text) if not key else await _run_polish(text, key)
    return {"status": "ok", "result": _polish_payload(outcome)}


@router.post("/api/writing/ai-polish/diff")
async def api_writing_ai_polish_diff(req: AIPolishReq, request: Request) -> Any:
    # P1-5 本机闸（怀疑者复核时补的第五条）：内部同样走循环出网烧配额。
    _require_localhost(request)
    text = req.text[:2000]
    if req.stream:
        return StreamingResponse(
            _polish_event_stream(request=request, text=text, with_diff=True),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    key = get_effective_api_key()
    outcome = _no_key_outcome(text) if not key else await _run_polish(text, key)
    return {"status": "ok", "result": _polish_diff_payload(text, outcome)}


def _get_writer_nlp() -> Any:
    try:
        return nlp
    except Exception:
        return None


@router.post("/api/writing/analyze")
def api_writing_analyze(req: WritingAnalyzeReq) -> Any:
    from delector.services.writing import analyze_essay_text

    return analyze_essay_text(req.text[:2000], _get_writer_nlp())


@router.post("/api/essays")
def create_essay(req: EssayCreateReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    a = analyze_essay_text(req.content[:5000], _get_writer_nlp())
    cefr = a.get("cefr", {}).get("recommended_level")
    with db_conn() as conn:
        cur = conn.execute(
            "INSERT INTO essays "
            "(title, content, analysis_json, cefr_level, error_count, sentence_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (req.title, req.content, json.dumps(a, ensure_ascii=False), cefr, a["error_count"], len(a["sentences"])),
        )
        eid = cur.lastrowid
    return {
        "id": eid,
        "title": req.title,
        "content": req.content,
        "analysis_json": a,
        "error_count": a["error_count"],
    }


@router.get("/api/essays")
def list_essays() -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, cefr_level, error_count, sentence_count, created_at, updated_at "
            "FROM essays ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/essays/{essay_id}")
def get_essay(essay_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    data = dict(row)
    if isinstance(data.get("analysis_json"), str):
        try:
            data["analysis_json"] = json.loads(data["analysis_json"])
        except Exception as exc:
            # Task 8b 真事故④：解析失败 MUST 留痕 —— 静默保持原始字符串会让响应形状（dict vs str）
            # 随数据质量悄悄变化，前端拿到两种形状却无人知。
            logging.getLogger("delector").warning(
                "essay #%s 的 analysis_json 解析失败（按原始字符串返回）：%s", essay_id, exc
            )
    return data


@router.put("/api/essays/{essay_id}")
def update_essay(essay_id: int, req: EssayUpdateReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        content = req.content if req.content is not None else row["content"]
        title = req.title if req.title is not None else row["title"]
        a = analyze_essay_text(content[:5000], _get_writer_nlp())
        now_str = datetime.utcnow().isoformat()
        conn.execute(
            "UPDATE essays SET title = ?, content = ?, analysis_json = ?, "
            "cefr_level = ?, error_count = ?, sentence_count = ?, updated_at = ? "
            "WHERE id = ?",
            (
                title,
                content,
                json.dumps(a, ensure_ascii=False),
                a.get("cefr", {}).get("recommended_level"),
                a["error_count"],
                len(a["sentences"]),
                now_str,
                essay_id,
            ),
        )
    return {"id": essay_id, "title": title, "content": content, "analysis_json": a, "error_count": a["error_count"]}


@router.delete("/api/essays/{essay_id}")
def delete_essay(essay_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        conn.execute("DELETE FROM essay_versions WHERE essay_id = ?", (essay_id,))
        conn.execute("DELETE FROM essays WHERE id = ?", (essay_id,))
    return {"status": "ok"}


@router.post("/api/writing/cards")
def save_writing_card(req: WritingCardReq) -> Any:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (req.essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    raw_analysis = row["analysis_json"]
    try:
        a = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
    except Exception:
        a = {}
    if not isinstance(a, dict):
        a = {}
    sentences = a.get("sentences", [])
    if not isinstance(sentences, list) or req.sentence_id < 0 or req.sentence_id >= len(sentences):
        raise HTTPException(400, "sentence_id 越界")
    sent = sentences[req.sentence_id]
    if not isinstance(sent, dict):
        raise HTTPException(400, "sentence_id 越界")
    spans = sent.get("spans", [])
    if not isinstance(spans, list) or req.span_index < 0 or req.span_index >= len(spans):
        raise HTTPException(400, "span_index 越界")
    sp = spans[req.span_index]
    if not isinstance(sp, dict):
        raise HTTPException(400, "span_index 越界")
    sentence_text = sent.get("text", "")
    card = GrammarCardReq(
        article_id=None,
        sentence_context=sentence_text,
        grammar_name=f"写作润色 · {sp.get('error_type', '')}",
        cefr_level=row["cefr_level"] or "B1",
        explanation_zh=sp.get("explanation_zh", ""),
        rule_formula=sp.get("corrected_form", ""),
        corrected_form=sp.get("corrected_form", ""),
        error_type=sp.get("error_type", ""),
    )
    return add_grammar_card(card)


@router.post("/api/essays/{essay_id}/versions")
def save_essay_version(essay_id: int, req: EssayVersionCreateReq) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        msg = req.message.strip() if (req.message and req.message.strip()) else "手动保存"
        cur = conn.execute(
            "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
            (essay_id, row["content"], row["analysis_json"], msg),
        )
        version_id = cur.lastrowid
        created_row = conn.execute("SELECT created_at FROM essay_versions WHERE id = ?", (version_id,)).fetchone()
        created_at = created_row["created_at"] if created_row else datetime.utcnow().isoformat()
    return {"version_id": version_id, "message": msg, "created_at": created_at}


@router.get("/api/essays/{essay_id}/versions")
def list_essay_versions(essay_id: int) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        rows = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE essay_id = ? ORDER BY id DESC",
            (essay_id,),
        ).fetchall()
        result = []
        for r in rows:
            raw_a = r["analysis_json"]
            try:
                a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a
                err_count = a.get("error_count", 0) if isinstance(a, dict) else 0
            except Exception:
                err_count = 0
            result.append(
                {
                    "id": r["id"],
                    "essay_id": r["essay_id"],
                    "message": r["message"],
                    "created_at": r["created_at"],
                    "error_count": err_count,
                }
            )
    return result


@router.get("/api/essays/{essay_id}/versions/{version_id}")
def get_essay_version(essay_id: int, version_id: int) -> Dict[str, Any]:
    with db_conn() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE id = ? AND essay_id = ?",
            (version_id, essay_id),
        ).fetchone()
        if not v:
            raise HTTPException(404, "version not found")
        raw_a = v["analysis_json"]
        try:
            a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a
            err_count = a.get("error_count", 0) if isinstance(a, dict) else 0
        except Exception:
            a = None
            err_count = 0
    return {
        "id": v["id"],
        "essay_id": v["essay_id"],
        "message": v["message"],
        "created_at": v["created_at"],
        "content": v["content"],
        "analysis_json": a,
        "error_count": err_count,
    }


@router.delete("/api/essays/{essay_id}/versions/{version_id}")
def delete_essay_version(essay_id: int, version_id: int, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    with db_conn() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id FROM essay_versions WHERE id = ? AND essay_id = ?", (version_id, essay_id)
        ).fetchone()
        if not v:
            raise HTTPException(404, "version not found")
        conn.execute("DELETE FROM essay_versions WHERE id = ? AND essay_id = ?", (version_id, essay_id))
    return {"status": "ok", "deleted_version_id": version_id}


@router.post("/api/essays/{essay_id}/restore")
def restore_essay_version(essay_id: int, req: EssayRestoreReq) -> Dict[str, Any]:
    from delector.services.writing import analyze_essay_text

    with db_conn() as conn:
        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        version = conn.execute(
            "SELECT * FROM essay_versions WHERE id = ? AND essay_id = ?", (req.version_id, essay_id)
        ).fetchone()
        if not version:
            raise HTTPException(404, "version not found")

        checkpoint_version_id = None
        if version["content"] != essay["content"]:
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
                (essay_id, essay["content"], essay["analysis_json"], f"恢复到版本 {req.version_id} 之前"),
            )
            checkpoint_version_id = cur.lastrowid
            a = analyze_essay_text(version["content"][:5000], _get_writer_nlp())
            now_str = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE essays SET content = ?, analysis_json = ?, cefr_level = ?, "
                "error_count = ?, sentence_count = ?, updated_at = ? WHERE id = ?",
                (
                    version["content"],
                    json.dumps(a, ensure_ascii=False),
                    a.get("cefr", {}).get("recommended_level"),
                    a["error_count"],
                    len(a["sentences"]),
                    now_str,
                    essay_id,
                ),
            )
        else:
            raw_a = essay["analysis_json"]
            a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a

    return {
        "id": essay_id,
        "content": version["content"],
        "analysis_json": a,
        "error_count": a["error_count"],
        "checkpoint_version_id": checkpoint_version_id,
    }


@router.post("/api/writing/apply")
def api_writing_apply(req: WritingApplyReq) -> Dict[str, Any]:
    from delector.services.essay_diff import diff_sentences, merge_sentences
    from delector.services.writing import analyze_essay_text

    hunks = diff_sentences(req.original_text, req.corrected_text)
    if any(idx < 0 or idx >= len(hunks) for idx in req.accepted_indices):
        raise HTTPException(400, "accepted_indices 越界")

    accepted = [i in set(req.accepted_indices) for i in range(len(hunks))]
    merged = merge_sentences(req.original_text, req.corrected_text, accepted)

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (req.essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")

        if req.accepted_indices and merged != row["content"]:
            a = analyze_essay_text(merged[:5000], _get_writer_nlp())
            now_str = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE essays SET title = ?, content = ?, analysis_json = ?, "
                "cefr_level = ?, error_count = ?, sentence_count = ?, updated_at = ? "
                "WHERE id = ?",
                (
                    row["title"],
                    merged,
                    json.dumps(a, ensure_ascii=False),
                    a.get("cefr", {}).get("recommended_level"),
                    a["error_count"],
                    len(a["sentences"]),
                    now_str,
                    req.essay_id,
                ),
            )
            msg = f"AI 润色 · 接受 {len(req.accepted_indices)}/{len(hunks)} 处"
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) VALUES (?, ?, ?, ?)",
                (req.essay_id, merged, json.dumps(a, ensure_ascii=False), msg),
            )
            version_id = cur.lastrowid
        else:
            version_id = None
            raw_analysis = row["analysis_json"]
            a = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
            merged = row["content"]

    return {
        "content": merged,
        "analysis_json": a,
        "error_count": a["error_count"],
        "version_id": version_id,
    }


# --- Syntax Radar Corpus Stats ---
class SyntaxStatsReq(BaseModel):
    article_id: int
    stats: Dict[str, Any]


@router.post("/api/syntax/stats")
async def api_syntax_stats_save(req: SyntaxStatsReq, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    background_tasks.add_task(upsert_corpus_syntax_stats, req.article_id, req.stats)
    return {"ok": True}


@router.get("/api/syntax/stats")
def api_syntax_stats_get() -> Any:
    return get_all_corpus_syntax_stats()


# --- Health Check ---
#
# 真健康端点：**必须真查数据库**。Go agent 的 supervisor 用它当启动探针与崩溃后
# 的存活探针（见 agent/internal/pythonsvc/supervisor.go 的 defaultHealthURL）。
# 此前探针指向 `GET /api/tools/`，而那个端点只枚举工具、**完全不碰数据库** ——
# 库损坏 / 磁盘掉线 / DATA_DIR 权限丢失时它照样回 200，agent 于是判定"服务健康"
# 并继续把调用打过来，报错延后到真正用到库的地方才炸，且现场已被探针掩盖。
#
# 纪律：
# 1. **真探测**：`SELECT 1` 走一次真实往返。它能捕获连接失败、库文件损坏
#    （sqlite 会在读页时报 disk image is malformed）与权限问题，且是常数级开销，
#    适合被 1s 间隔的探针高频调用。不用 `PRAGMA quick_check`（全库扫描，探针
#    每秒调一次太贵），也不缓存结果（缓存等于把本端点退化成又一个"进程活着吗"）。
# 2. **不泄露**：失败响应只带状态与一句人类可读原因。库路径、异常类型、栈一律
#    只进服务端日志（`exc_info=True`）—— 探针响应会流经监控与日志聚合系统，
#    裸路径在那些系统里等同对外泄露部署布局。真实原因必须留痕，不能因"不外泄"而丢。
# 3. **不挂 `_require_localhost`**：只读 GET 不挂本机闸是本仓库惯例（全仓 16 处
#    该闸全在写 / 密钥 / 备份类端点）。健康端点是纯只读、无副作用、且探针本就在
#    同机（agent 托管 127.0.0.1:8001）；给它挂闸只会让"闸把人挡在门外"被误读成
#    "服务不健康"，反而制造假故障。
_HEALTH_DETAIL_UNAVAILABLE = "本地数据库暂时不可用，请稍后重试"


@router.get("/api/health")
def api_health() -> Any:
    """健康探针：库可用回 200，不可用回 503（Service Unavailable）。

    503 而非 500：语义上"依赖不可用、稍后可能自愈"，与真正的服务端缺陷区分开，
    探针方（agent supervisor、LB）才能把它当可重试信号而非立即告警。
    """
    try:
        with db_conn() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:
        import logging

        # 真实原因（含路径与栈）只进服务端日志：运维需要它定位，用户不需要，
        # 而探针响应是会被外部系统读取的。
        logging.getLogger("delector").exception("health check failed: database unavailable")
        return Response(
            status_code=503,
            content=json.dumps(
                {
                    "status": "unhealthy",
                    "detail": _HEALTH_DETAIL_UNAVAILABLE,
                    "app": "delector",
                    "version": APP_VERSION,
                },
                ensure_ascii=False,
            ),
            media_type="application/json; charset=utf-8",
        )
    # 身份字段（ADR-0020 §4 前置①）：桌面壳启动时必须能凭 /api/health 分辨「这是不是
    # DeLector」，以消除「复用别人的端口 / 跑旧进程」两类静默失败。库这一层通时就给出
    # 应用名与版本。
    #
    # **503 分支同样给身份**（这一点是契约，不是"额外暴露"）：`server_lifecycle.probe_identity`
    # 的契约是「**接受 503、只看身份**」—— 库坏但进程是 DeLector，仍算 DeLector。若 503 不带
    # 身份，`start.py` 第二次启动会把「自己的降级实例」误报成「端口被其他程序占用」并 `exit(1)`
    # —— 正是本任务要消灭的盲误判之镜像。身份之外（路径/栈/异常类名）仍只进服务端日志。
    return {"status": "ok", "database": "ok", "app": "delector", "version": APP_VERSION}
