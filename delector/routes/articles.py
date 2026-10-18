# -*- coding: utf-8 -*-
"""文章与阅读域路由：文章摄入、RSS/Feed 抓取、文章阅读、批注、讲义导出及完形填空。"""

# mypy: disable-error-code="misc,untyped-decorator"

import asyncio
import json
import logging
import re
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from delector.core.database import (
    _require_localhost,
    db_conn,
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    ingest_article,
    log_study_event,
)
from delector.core.security import (
    PRESET_FEEDS,
    clean_html_to_article,
    fetch_remote_html,
    is_safe_public_url,
    parse_rss_feed,
)
from delector.core.utils import _attachment_headers
from delector.nlp_engine.processor import (
    PROCESSED_JSON_VERSION,
    get_cefr_level,
    nlp,
    process_german_text,
)
from delector.routes.syntax_hard import invalidate_rank_cache
from delector.services import llm_client

router = APIRouter()


class IngestReq(BaseModel):
    title: Optional[str] = "Untitled"
    # 局域网可达 + spaCy 全文重算，必须有上限（防超大文本打满 NLP 与磁盘）
    raw_text: str = Field(..., max_length=100_000)


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
    #   或老备份还原进来的行）当场用 json_extract 从 blob 取——只有这些少数行付
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
# 权衡（为什么 per-article 而不是全局锁）：全局锁会把"8 篇不同旧文并发首开"
# 也串行化——spaCy 计算 0.5~1.7s/篇，串行即 4~14s 墙钟，比并发重算慢得多；
# per-article 锁只让同一篇的并发互斥（恰好就是我们要挡的重复计算），不同篇照常并行。
#
# 字典清理策略：单用户规模下不做清理——每把 threading.Lock ~100B，条目数上限
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
            # P1-8 single-flight：拿 per-article 锁 + 锁内重检——等锁期间别的请求
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
                    # 提交必须在释放锁之前完成：重检读的是"已提交"数据，若 commit
                    # 留在 handler 末尾（锁外），等锁者拿锁重检时读到的仍是陈旧值 ⇒
                    # single-flight 空转（实测 8 并发算 2 次）。提前 commit 只改提交时机、
                    # 不改事务内容：仍只有这一条 UPDATE，异常时不走到这行、整体回滚。
                    conn.commit()
        if isinstance(pj, dict):
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
