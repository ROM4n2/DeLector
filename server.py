import os
import time
import math
import json
import tempfile
import secrets
import re
import asyncio
import hashlib
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import httpx

def load_env():
    try:
        import dotenv
        dotenv.load_dotenv(override=True)
    except Exception:
        pass
    for base_dir in [os.path.dirname(__file__), os.getcwd()]:
        env_file = os.path.join(base_dir, ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'").strip('"')
                            if k:
                                os.environ[k] = v
            except Exception:
                pass

load_env()

# --- 1. Database & Settings Layer ---
from database import (
    DATA_DIR,
    AUDIO_CACHE_DIR,
    PROGRESS_DB_PATH,
    get_db_path,
    get_progress_db_path,
    get_db,
    get_progress_db,
    init_progress_db,
    log_study_event,
    init_db,
    get_setting,
    set_setting,
    get_effective_api_key,
    get_effective_api_base_url,
    get_effective_api_model,
    PRESET_ARTICLES,
    ingest_article,
    seed_preset_articles,
    VOCAB_MODEL,
    GRAMMAR_MODEL,
    export_anki_deck,
    export_a1_anki_deck,
    get_cache_info,
    prune_audio_cache,
    BACKUP_FORMAT_VERSION,
    BACKUP_SETTINGS_WHITELIST,
    _BACKUP_TABLES,
    _PROGRESS_TABLES,
    _require_localhost,
    _rows_to_tuples,
    build_backup_payload,
    _pending_backup,
    _pending_wb,
    _db_snapshot_guard,
    _replace_tables,
    get_prep_saved,
    add_prep_saved,
)

# --- 2. NLP & CEFR Tagging ---
from nlp import (
    spacy,
    nlp,
    NLP_ENGINE,
    NLP_ENGINE_DETAIL,
    SPACY_MODEL_CANDIDATES,
    AUTO_DOWNLOAD_MODEL,
    _load_spacy_model,
    CEFR_DICT,
    get_cefr_level,
    calculate_cefr_stats,
    _process_german_text_pure_python,
    process_german_text,
    SYSTEM_GRAMMAR_PROMPT,
)

# --- 3. Security, SSRF & Feed Utilities ---
from security import (
    _resolve_ssrf_targets,
    _IETF_PROTOCOL_ASSIGNMENTS,
    _IPV6_DENY_PREFIXES,
    _is_blocked_addr,
    is_safe_public_url,
    clean_html_to_article,
    MAX_REDIRECT_HOPS,
    fetch_remote_html,
    PRESET_FEEDS,
    parse_rss_feed,
)

__all__ = [
    "spacy",
    "nlp",
    "NLP_ENGINE",
    "NLP_ENGINE_DETAIL",
    "SPACY_MODEL_CANDIDATES",
    "AUTO_DOWNLOAD_MODEL",
    "_load_spacy_model",
    "CEFR_DICT",
    "get_cefr_level",
    "calculate_cefr_stats",
    "_process_german_text_pure_python",
    "process_german_text",
    "SYSTEM_GRAMMAR_PROMPT",
    "DATA_DIR",
    "AUDIO_CACHE_DIR",
    "PROGRESS_DB_PATH",
    "get_db_path",
    "get_progress_db_path",
    "get_db",
    "get_progress_db",
    "init_progress_db",
    "log_study_event",
    "init_db",
    "get_setting",
    "set_setting",
    "get_effective_api_key",
    "get_effective_api_base_url",
    "get_effective_api_model",
    "PRESET_ARTICLES",
    "ingest_article",
    "seed_preset_articles",
    "VOCAB_MODEL",
    "GRAMMAR_MODEL",
    "export_anki_deck",
    "get_cache_info",
    "prune_audio_cache",
    "BACKUP_FORMAT_VERSION",
    "BACKUP_SETTINGS_WHITELIST",
    "_BACKUP_TABLES",
    "_PROGRESS_TABLES",
    "_require_localhost",
    "_rows_to_tuples",
    "build_backup_payload",
    "_pending_backup",
    "_pending_wb",
    "_db_snapshot_guard",
    "_replace_tables",
    "get_prep_saved",
    "add_prep_saved",
    "_resolve_ssrf_targets",
    "_IETF_PROTOCOL_ASSIGNMENTS",
    "_IPV6_DENY_PREFIXES",
    "_is_blocked_addr",
    "is_safe_public_url",
    "clean_html_to_article",
    "MAX_REDIRECT_HOPS",
    "fetch_remote_html",
    "PRESET_FEEDS",
    "parse_rss_feed",
]

from core_dict import lookup_core_vocab
from linguistics import (lookup_irregular_verb, lookup_linguistics_ext, split_komposita,
                         lookup_prep_collocations, build_prep_matrix)
from syntax_tree import analyze_syntax_tree

# --- 4. FastAPI Application ---
app = FastAPI(title="DeLector")
init_db()

# 前端资源必须每次回源校验：裸 StaticFiles 不发 Cache-Control，浏览器于是走
# 启发式新鲜度（约 Last-Modified 距今时长的 10%），可能一段时间内直接用本地副本。
# main.js 的 ES module import 是裸路径（./core.js 等），没有 ?v= 版本号可 bust，
# 一旦被缓存住就会加载旧代码。
# 选 no-cache 而不是 no-store：no-cache 仍允许缓存、只是强制回源校验，
# 配合 StaticFiles 已有的 ETag 能命中 304 Not Modified，几乎不浪费流量；
# no-store 会禁掉全部缓存，既全量重传也会削弱本项目 PWA 的离线能力。
FRONTEND_NO_CACHE_SUFFIXES = (".html", ".htm", ".js", ".mjs", ".css")
FRONTEND_NO_CACHE_TYPES = (
    "text/html", "text/css",
    "text/javascript", "application/javascript", "application/ecmascript",
)

@app.middleware("http")
async def add_frontend_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    # API 自己决定缓存语义，不由这里代劳；音频（.cache/audio 下的 MP3）也只经
    # /api/audio/tts 提供，是内容寻址的、可长期缓存，一并放行。
    if path.startswith("/api/"):
        return response
    # 后缀优先：Windows 的 mimetypes 会读注册表，.js 的 content-type 并不总是可靠。
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    is_frontend_asset = (
        path.lower().endswith(FRONTEND_NO_CACHE_SUFFIXES)
        or path.endswith("/")  # 目录索引 → index.html（StaticFiles html=True）
        or content_type in FRONTEND_NO_CACHE_TYPES
    )
    if is_frontend_asset:
        response.headers["Cache-Control"] = "no-cache"
    return response

class IngestReq(BaseModel):
    title: Optional[str] = "Untitled"
    raw_text: str

class VocabCardReq(BaseModel):
    article_id: Optional[int] = None
    word: str
    lemma: str
    pos: Optional[str] = ""
    gender: Optional[str] = ""
    plural: Optional[str] = ""
    cefr_level: Optional[str] = "A1"
    definition_zh: str
    sentence_context: str

class GrammarCardReq(BaseModel):
    article_id: Optional[int] = None
    sentence_context: str
    grammar_name: str
    cefr_level: str
    explanation_zh: str
    rule_formula: Optional[str] = ""
    corrected_form: Optional[str] = ""
    error_type: Optional[str] = ""

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

@app.post("/api/articles/ingest-url")
async def ingest_from_url(req: IngestUrlReq):
    if not is_safe_public_url(req.url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")

    raw_html = await fetch_remote_html(req.url)
    title, body_text = clean_html_to_article(raw_html)
    if not body_text or len(body_text.strip()) < 30:
        raise HTTPException(400, "未能从该网页提取到有效的德语正文，请尝试直接复制粘贴")

    final_title = req.title.strip() if req.title else title
    art_id = await asyncio.to_thread(ingest_article, final_title, body_text, None, req.url)
    with get_db() as conn:
        row = conn.execute("SELECT processed_json FROM articles WHERE id = ?", (art_id,)).fetchone()
        pj = json.loads(row["processed_json"]) if row else {}
    return {"article_id": art_id, "title": final_title, "char_count": len(body_text), "stats": pj.get("stats", {})}

@app.get("/api/feed/sources")
def get_feed_sources():
    return {"sources": PRESET_FEEDS}

@app.get("/api/feed/items")
async def get_feed_items(url: str):
    if not is_safe_public_url(url):
        raise HTTPException(400, "无效网址或受限制的内部网络地址 (SSRF Protection)")
    raw_xml = await fetch_remote_html(url)
    items = parse_rss_feed(raw_xml)
    return {"url": url, "count": len(items), "items": items}

@app.post("/api/articles/ingest")
def ingest(req: IngestReq):
    art_id = ingest_article(req.title or "Untitled", req.raw_text)
    return {"article_id": art_id, "title": req.title}


@app.get("/api/articles")
def list_articles():
    with get_db() as conn:
        rows = conn.execute("SELECT id, title, created_at, length(raw_text) as char_count, raw_text, processed_json FROM articles ORDER BY id DESC").fetchall()
        result = []
        for r in rows:
            d = {"id": r["id"], "title": r["title"], "created_at": r["created_at"], "char_count": r["char_count"]}
            try:
                pj = json.loads(r["processed_json"])
                if "stats" not in pj:
                    pj = process_german_text(r["raw_text"])
                    conn.execute("UPDATE articles SET processed_json = ? WHERE id = ?", (json.dumps(pj, ensure_ascii=False), r["id"]))
                d["stats"] = pj.get("stats", {})
            except Exception:
                d["stats"] = {}
            result.append(d)
        return result

@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        data = dict(row)
        pj = json.loads(data["processed_json"])
        if "stats" not in pj or pj.get("version") != "3.4.0":
            pj = process_german_text(data["raw_text"])
            conn.execute("UPDATE articles SET processed_json = ? WHERE id = ?", (json.dumps(pj, ensure_ascii=False), article_id))
        data.update(pj)
        return data

@app.delete("/api/articles/{article_id}")
def delete_article(article_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Article not found")
        conn.execute("DELETE FROM reading_notes WHERE article_id = ?", (article_id,))
        conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        return {"deleted": True, "article_id": article_id}

@app.post("/api/lookup/grammar")
async def lookup_grammar(req: GrammarLookupReq):
    key = get_effective_api_key()
    if not key:
        return {
            "grammar_name": f"语法考点辨析 ({req.target_phrase})",
            "cefr_level": "A1",
            "explanation_zh": "请在右上角「⚙️ 设置」中配置 API Key 获取实时歌德大纲 AI 分析。",
            "rule_formula": "Grammar Pattern",
            "collocations": [f"{req.target_phrase} (常用释义)"]
        }

    base_url = get_effective_api_base_url().rstrip('/')
    model = get_effective_api_model()
    user_content = f"句子: \"{req.sentence}\"\n目标词/短语: \"{req.target_phrase}\""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_GRAMMAR_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if getattr(resp, "status_code", 200) != 200:
                raise HTTPException(status_code=502, detail=f"AI 服务异常 ({getattr(resp, 'status_code', 500)})")
            try:
                data = resp.json()
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回非 JSON 响应")
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务响应格式异常")
            try:
                return json.loads(content)
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回内容非 JSON")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="AI 服务连接失败")

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

@app.post("/api/lookup/vocab")
async def lookup_vocab(req: VocabLookupReq):
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
                "source": "local_dict"
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
                    "source": "linguistics_ext"
                }
                break

    # Tier 2: AI 兜底（仅当本地无释义且有 key）
    if not res.get("definition_zh"):
        key = get_effective_api_key()
        if not key:
            res = {
                "definition_zh": "",
                "plural": "",
                "synonyms": [],
                "source": "none"
            }
        else:
            base_url = get_effective_api_base_url().rstrip('/')
            model = get_effective_api_model()
            user_content = f"句子: \"{req.sentence}\"\n目标词汇: \"{req.target_word}\""
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": SYSTEM_VOCAB_PROMPT},
                                {"role": "user", "content": user_content}
                            ],
                            "response_format": {"type": "json_object"}
                        }
                    )
                    if resp.status_code != 200:
                        res = {
                            "definition_zh": "",
                            "plural": "",
                            "synonyms": [],
                            "source": "ai_error"
                        }
                    else:
                        content = resp.json()["choices"][0]["message"]["content"]
                        res = json.loads(content)
                        res["source"] = "ai"
            except Exception:
                res = {
                    "definition_zh": "",
                    "plural": "",
                    "synonyms": [],
                    "source": "ai_exception"
                }

    # Morphology & Linguistics Layer:
    # 1. Irregular / Strong verbs Stammformen（始终附；释义只在本地兜底没出时回填）
    stamm = lookup_irregular_verb(req.lemma or req.target_word)
    if stamm:
        inf = getattr(stamm, "infinitiv", None) or (stamm.get("infinitiv") if hasattr(stamm, "get") else "")
        praet = getattr(stamm, "praeteritum", None) or (stamm.get("praeteritum") if hasattr(stamm, "get") else "")
        p2 = getattr(stamm, "partizip2", None) or (stamm.get("partizip2") if hasattr(stamm, "get") else "")
        hilf = getattr(stamm, "hilfsverb", None) or (stamm.get("hilfsverb") if hasattr(stamm, "get") else "")
        stamm_def = getattr(stamm, "definition_zh", None) or (stamm.get("definition_zh") if hasattr(stamm, "get") else "")

        res["stammformen"] = {
            "infinitiv": inf,
            "praeteritum": praet,
            "partizip2": p2,
            "hilfsverb": hilf
        }
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
                sub_defs = [p.get("definition_zh") or p.get("def_zh") for p in parts if (p.get("definition_zh") or p.get("def_zh"))]
                if sub_defs:
                    res["definition_zh"] = " + ".join(sub_defs)
                    if res.get("source") in ("none", "ai_error", "ai_exception"):
                        res["source"] = "linguistics"

    # 3. 固定介词搭配（Verben/Adjektive mit Präpositionen）
    # 挂在同一个响应里而不是新开端点：抽屉那几个 banner box 的渲染/拆除都假定
    # 数据来自同一个响应对象，新端点要在前端引入第二个异步状态与竞态处理。
    praep = (lookup_prep_collocations(req.lemma or "")
             or lookup_prep_collocations(req.target_word))
    if praep:
        res["praepositionen"] = praep

    return res


# ── Präpositionen-Matrix ─────────────────────────────────────────────────────
_prep_matrix_response_cache = None


def get_prep_matrix_with_cefr():
    """矩阵响应构建 + CEFR 注入，进程级缓存。

    CEFR 在这一层而不是 linguistics.build_prep_matrix 里注入：
    get_cefr_level 是 server 的启发式（含长度 fallback），留在这层才能
    保证「展示标签」变化时不污染纯函数的守恒契约测试。
    组间顺序同理 —— 「常用者优先」是对用户可见面的要求，属呈现策略。
    """
    global _prep_matrix_response_cache
    if _prep_matrix_response_cache is None:
        groups = []
        for praep, by_case in build_prep_matrix().items():
            entries_by_case = {
                kasus: [{**e, "cefr": get_cefr_level(e["lemma"])} for e in entries]
                for kasus, entries in by_case.items()
            }
            groups.append({
                "praeposition": praep,
                "total": sum(len(v) for v in entries_by_case.values()),
                "cases": entries_by_case,
            })
        # 同总数时按介词字母序兜底，避免 dict 插入序泄漏成不稳定的呈现顺序
        groups.sort(key=lambda g: (-g["total"], g["praeposition"]))
        _prep_matrix_response_cache = {"groups": groups}
    return _prep_matrix_response_cache


@app.get("/api/prep/matrix")
def api_prep_matrix():
    return get_prep_matrix_with_cefr()


class PrepSavedReq(BaseModel):
    lemma: str
    praep: str
    kasus: str


@app.get("/api/prep/saved")
def api_prep_saved():
    """返回当前用户已入卡的搭配 key 列表。"""
    return {"keys": sorted(get_prep_saved())}


@app.post("/api/prep/saved")
def api_add_prep_saved(req: PrepSavedReq):
    """记录一条搭配已入卡。"""
    add_prep_saved(req.lemma, req.praep, req.kasus)
    return {"status": "ok"}



# ── FSRS (Free Spaced Repetition Scheduler) DSR Engine ────────────────────────

def _calc_fsrs_step(
    grade: int,
    rep: int = 0,
    interval: int = 1,
    ef: float = 2.5,
    elapsed_days: Optional[int] = None,
    target_retention: float = 0.90
) -> Tuple[int, int, float, str]:
    """
    Core single-step FSRS mathematical state transition based on DSR model:
    grade: 1 (Forgot/Again), 2 (Hard), 3 (Good), 4 (Easy)
    """
    grade = max(1, min(4, int(grade)))
    target_retention = max(0.70, min(0.98, float(target_retention)))

    if rep <= 0:
        # Initial review calibration
        s0_map = {1: 0.5, 2: 1.8, 3: 3.6, 4: 8.5}
        d0 = max(1.0, min(10.0, 8.0 - (grade - 1) * 1.8))
        s_prime = s0_map.get(grade, 3.6)
        d_prime = d0
        new_rep = 1 if grade >= 2 else 0
    else:
        # Subsequent review transition
        s = max(0.1, float(interval))
        d = max(1.0, min(10.0, float(ef)))
        t = max(1.0, float(elapsed_days if elapsed_days is not None else interval))

        # Retrievability power-law decay
        r = (1.0 + (19.0 / 81.0) * (t / s)) ** (-0.5)
        r = max(0.01, min(0.99, r))

        # Difficulty update with mean reversion to D0(3) = 4.4
        d0_3 = 4.4
        delta_d = -(grade - 3) * 0.8
        d_prime = max(1.0, min(10.0, 0.1 * d0_3 + 0.9 * (d + delta_d)))

        if grade == 1:
            # Lapse / Forgot
            new_rep = 0
            s_prime = max(0.4, min(s, 0.6 * (d_prime ** -0.3) * ((s + 1.0) ** 0.4)))
        else:
            # Successful recall
            new_rep = rep + 1
            penalty_map = {2: 0.6, 3: 1.0, 4: 1.4}
            penalty = penalty_map.get(grade, 1.0)
            factor = math.exp(1.0) * (11.0 - d_prime) * (s ** -0.2) * (math.exp((1.0 - r) * 0.9) - 1.0) * penalty
            s_prime = max(0.4, s * (1.0 + factor))

    # Calculate scheduled interval based on target retention
    if abs(target_retention - 0.90) < 1e-6:
        scheduled_days = s_prime
    else:
        scheduled_days = s_prime * (81.0 / 19.0) * (target_retention ** (-2.0) - 1.0)

    new_interval = max(1, int(round(scheduled_days + 1e-9)))
    new_ef = round(d_prime, 2)
    due_date = (datetime.now() + timedelta(days=new_interval)).strftime('%Y-%m-%d')
    return new_rep, new_interval, new_ef, due_date


def get_fsrs_next_intervals(
    rep: int = 0,
    interval: int = 1,
    ef: float = 2.5,
    elapsed_days: Optional[int] = None,
    target_retention: float = 0.90
) -> Dict[int, int]:
    """
    Precalculate scheduled intervals for all 4 rating grades (1: Again, 2: Hard, 3: Good, 4: Easy).
    """
    return {
        g: _calc_fsrs_step(g, rep, interval, ef, elapsed_days, target_retention)[1]
        for g in (1, 2, 3, 4)
    }


def calculate_fsrs(
    grade: int,
    rep: int = 0,
    interval: int = 1,
    ef: float = 2.5,
    elapsed_days: Optional[int] = None,
    target_retention: float = 0.90
) -> Tuple[int, int, float, str, Dict[int, int]]:
    """
    Calculate next FSRS schedule state.
    Returns: (new_rep, new_interval, new_ef, due_date, next_intervals)
    """
    new_rep, new_interval, new_ef, due_date = _calc_fsrs_step(grade, rep, interval, ef, elapsed_days, target_retention)
    next_intervals = get_fsrs_next_intervals(new_rep, new_interval, new_ef, target_retention=target_retention)
    return new_rep, new_interval, new_ef, due_date, next_intervals


def calculate_sm2(grade: int, rep: int = 0, interval: int = 1, ef: float = 2.5) -> Tuple[int, int, float, str]:
    """
    Backward-compatible SM-2 wrapper over modern FSRS scheduler.
    Returns: (new_rep, new_interval, new_ef, due_date)
    """
    new_rep, new_interval, new_ef, due_date, _ = calculate_fsrs(grade, rep, interval, ef)
    return new_rep, new_interval, new_ef, due_date


@app.post("/api/cards/vocab")
def add_vocab_card(req: VocabCardReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO vocab_cards (article_id, word, lemma, pos, gender, plural, cefr_level, definition_zh, sentence_context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (req.article_id, req.word, req.lemma, req.pos, req.gender, req.plural or "", req.cefr_level, req.definition_zh, req.sentence_context)
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.word)
    return {"status": "ok", "id": card_id, "word": req.word, "plural": req.plural or ""}

@app.post("/api/cards/grammar")
def add_grammar_card(req: GrammarCardReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO grammar_cards (article_id, sentence_context, grammar_name, cefr_level, explanation_zh, rule_formula, corrected_form, error_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (req.article_id, req.sentence_context, req.grammar_name, req.cefr_level, req.explanation_zh, req.rule_formula or "", req.corrected_form or "", req.error_type or "")
        )
        card_id = cur.lastrowid
    log_study_event("add_card", card_id, req.grammar_name)
    return {"status": "ok", "id": card_id}

@app.get("/api/cards")
def get_cards():
    with get_db() as conn:
        v = [dict(r) for r in conn.execute(
            "SELECT * FROM vocab_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
        ).fetchall()]
        g = [dict(r) for r in conn.execute(
            "SELECT * FROM grammar_cards ORDER BY mastered ASC, wrong_count DESC, id DESC"
        ).fetchall()]
        for card in v + g:
            card["next_intervals"] = get_fsrs_next_intervals(
                card.get("repetition_count") or 0,
                card.get("interval_days") or 1,
                card.get("ease_factor") or 2.5
            )
        return {"vocab_cards": v, "grammar_cards": g}

# --- Phase A: Delete & Master ---

@app.delete("/api/cards/{card_type}/{card_id}")
def delete_card(card_type: str, card_id: int):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(f"DELETE FROM {tbl} WHERE id = ?", (card_id,))
    log_study_event("delete_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "deleted_id": card_id, "card_type": card_type}

class MasterReq(BaseModel):
    mastered: bool

@app.patch("/api/cards/{card_type}/{card_id}/master")
def toggle_master(card_type: str, card_id: int, req: MasterReq):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    now_ts = datetime.now().isoformat() if req.mastered else None
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")
        conn.execute(
            f"UPDATE {tbl} SET mastered = ?, mastered_at = ? WHERE id = ?",
            (1 if req.mastered else 0, now_ts, card_id)
        )
    if req.mastered:
        log_study_event("master_card", card_id, f"{card_type}:{card_id}")
    return {"status": "ok", "id": card_id, "mastered": req.mastered}

# --- Phase B: Quiz Record ---

class QuizRecordReq(BaseModel):
    card_id: int
    card_type: str  # 'vocab' | 'grammar'
    mode: str       # 'flashcard' | 'dictation' | 'choice'
    correct: bool

@app.post("/api/quiz/record")
def record_quiz(req: QuizRecordReq):
    if req.card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if req.card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT id FROM {tbl} WHERE id = ?", (req.card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {req.card_id} not found")
        if req.correct:
            conn.execute(f"UPDATE {tbl} SET correct_count = correct_count + 1 WHERE id = ?", (req.card_id,))
        else:
            conn.execute(f"UPDATE {tbl} SET wrong_count = wrong_count + 1 WHERE id = ?", (req.card_id,))
    with get_progress_db() as conn:
        conn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (req.card_id, req.card_type, req.mode, 1 if req.correct else 0)
        )
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("INSERT OR IGNORE INTO daily_summary (date) VALUES (?)", (today,))
        conn.execute(
            "UPDATE daily_summary SET quiz_sessions = quiz_sessions + 1, study_minutes = study_minutes + 1 WHERE date = ?",
            (today,)
        )
    return {"status": "ok"}

# --- Phase C: Progress Stats ---

class ReadLogReq(BaseModel):
    article_id: int
    title: Optional[str] = ""

@app.post("/api/progress/log-read")
def log_article_read(req: ReadLogReq):
    log_study_event("read_article", req.article_id, req.title or "", minutes=8)
    return {"status": "ok"}

@app.get("/api/progress/stats")
def get_progress_stats():
    from datetime import timedelta
    # --- main db ---
    with get_db() as conn:
        total_vocab   = conn.execute("SELECT COUNT(*) FROM vocab_cards").fetchone()[0]
        total_grammar = conn.execute("SELECT COUNT(*) FROM grammar_cards").fetchone()[0]
        mastered_vocab   = conn.execute("SELECT COUNT(*) FROM vocab_cards WHERE mastered=1").fetchone()[0]
        mastered_grammar = conn.execute("SELECT COUNT(*) FROM grammar_cards WHERE mastered=1").fetchone()[0]
        total_articles = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

        # CEFR breakdown (both tables combined)
        cefr_counts: Dict[str, int] = {"A1": 0, "A2": 0, "B1": 0, "B2": 0, "C1": 0}
        for row in conn.execute("SELECT cefr_level, COUNT(*) as cnt FROM vocab_cards GROUP BY cefr_level"):
            lvl = row["cefr_level"] or "A1"
            if lvl in cefr_counts:
                cefr_counts[lvl] += row["cnt"]
        for row in conn.execute("SELECT cefr_level, COUNT(*) as cnt FROM grammar_cards GROUP BY cefr_level"):
            lvl = row["cefr_level"] or "A1"
            if lvl in cefr_counts:
                cefr_counts[lvl] += row["cnt"]

        # Quiz accuracy from card tables
        vc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM vocab_cards").fetchone()
        gc_row = conn.execute("SELECT SUM(correct_count) as c, SUM(wrong_count) as w FROM grammar_cards").fetchone()
        total_correct = (vc_row["c"] or 0) + (gc_row["c"] or 0)
        total_wrong   = (vc_row["w"] or 0) + (gc_row["w"] or 0)
        total_attempts = total_correct + total_wrong
        accuracy_pct = round(total_correct / total_attempts * 100, 1) if total_attempts > 0 else 0.0

        # Top error-prone cards (wrong_count > 2× correct_count, limit 5)
        top_errors = []
        for row in conn.execute(
            "SELECT id, word, definition_zh, wrong_count, correct_count FROM vocab_cards "
            "WHERE wrong_count > 0 ORDER BY (wrong_count * 1.0 / MAX(correct_count+1, 1)) DESC LIMIT 5"
        ):
            top_errors.append(dict(row))

    # --- progress db ---
    with get_progress_db() as conn:
        # 30-day daily trend
        today = datetime.now().date()
        trend = []
        for i in range(29, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            row = conn.execute("SELECT * FROM daily_summary WHERE date = ?", (d,)).fetchone()
            if row:
                trend.append(dict(row))
            else:
                trend.append({"date": d, "cards_added": 0, "cards_mastered": 0,
                               "articles_read": 0, "quiz_sessions": 0, "study_minutes": 0})

        # Streak calculation
        streak = 0
        check_date = today
        # treat today as active if it has any study_log entries
        for _ in range(365):
            ds = check_date.isoformat()
            entry = conn.execute("SELECT 1 FROM study_log WHERE date(logged_at)=? LIMIT 1", (ds,)).fetchone()
            if entry:
                streak += 1
                check_date = check_date - timedelta(days=1)
            else:
                break

        total_quiz_sessions = conn.execute("SELECT SUM(quiz_sessions) FROM daily_summary").fetchone()[0] or 0
        total_study_minutes = conn.execute("SELECT SUM(study_minutes) FROM daily_summary").fetchone()[0] or 0

    total_cards    = total_vocab + total_grammar
    total_mastered = mastered_vocab + mastered_grammar

    # Milestones
    milestones = [
        {"id": "first_card",     "title": "初临纸页",   "desc": "制作了第一张卡片",       "icon": "🌱", "unlocked": total_cards >= 1},
        {"id": "first_article",  "title": "开卷有益",   "desc": "研读了第一篇德语文章",   "icon": "📖", "unlocked": total_articles >= 1},
        {"id": "master_10",      "title": "小试牛刀",   "desc": "斩获 10 张已掌握卡片",   "icon": "⚔️", "unlocked": total_mastered >= 10},
        {"id": "master_50",      "title": "千锤百炼",   "desc": "斩获 50 张已掌握卡片",   "icon": "🛡️", "unlocked": total_mastered >= 50},
        {"id": "master_100",     "title": "百词斩将",   "desc": "斩获 100 张已掌握卡片",  "icon": "🏆", "unlocked": total_mastered >= 100},
        {"id": "master_200",     "title": "词海无涯",   "desc": "斩获 200 张已掌握卡片",  "icon": "👑", "unlocked": total_mastered >= 200},
        {"id": "streak_3",       "title": "三日不绝",   "desc": "连续打卡 3 天",          "icon": "🔥", "unlocked": streak >= 3},
        {"id": "streak_7",       "title": "一周常胜",   "desc": "连续打卡 7 天",          "icon": "⚡", "unlocked": streak >= 7},
        {"id": "streak_30",      "title": "月光苦读者", "desc": "连续打卡 30 天",         "icon": "🌙", "unlocked": streak >= 30},
    ]

    return {
        "total_cards":    total_cards,
        "total_vocab":    total_vocab,
        "total_grammar":  total_grammar,
        "total_mastered": total_mastered,
        "mastered_vocab":   mastered_vocab,
        "mastered_grammar": mastered_grammar,
        "total_articles": total_articles,
        "streak":         streak,
        "total_quiz_sessions": total_quiz_sessions,
        "total_study_minutes": total_study_minutes,
        "total_attempts": total_attempts,
        "accuracy_pct":   accuracy_pct,
        "cefr_counts":    cefr_counts,
        "top_errors":     top_errors,
        "trend":          trend,
        "milestones":     milestones,
    }

@app.get("/api/cards/export/apkg")
def export_apkg():
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "DeLector_Deck.apkg")
    export_anki_deck(path)
    return FileResponse(path, filename="DeLector_Deck.apkg", media_type="application/octet-stream")


# --- Goethe-Zertifikat A1 Wortliste & Sprechen Lab ---
@app.get("/api/a1/topics")
def get_a1_topics():
    import a1_dict
    counts = {}
    for entry in a1_dict.GOETHE_A1_VOCAB.values():
        t = entry.get("topic", "phrases")
        counts[t] = counts.get(t, 0) + 1

    return [
        {
            "key": key,
            "label": label,
            "keywords": kw,
            "count": counts.get(key, 0),
        }
        for key, label, kw in a1_dict.A1_TOPICS
    ]


@app.get("/api/a1/vocab")
def get_a1_vocab(topic: Optional[str] = None, q: Optional[str] = None):
    import a1_dict
    res = list(a1_dict.GOETHE_A1_VOCAB.values())
    if topic:
        res = [w for w in res if w.get("topic") == topic]
    if q:
        query = q.strip().lower()
        res = [
            w for w in res
            if query in w.get("word", "").lower()
            or query in w.get("lemma", "").lower()
            or query in w.get("definition_zh", "").lower()
        ]
    return res


@app.get("/api/a1/sprechen/teil2")
def get_a1_sprechen_teil2(topic: Optional[str] = None):
    import a1_dict
    cards = a1_dict.A1_SPRECHEN_TEIL2
    if topic:
        cards = [c for c in cards if c.get("topic_id") == topic]
    return cards


@app.get("/api/a1/sprechen/teil3")
def get_a1_sprechen_teil3():
    import a1_dict
    return a1_dict.A1_SPRECHEN_TEIL3


@app.get("/api/a1/export/anki")
def export_a1_anki():
    tmp = tempfile.gettempdir()
    path = os.path.join(tmp, "Goethe_A1_Wortliste.apkg")
    export_a1_anki_deck(path)
    return FileResponse(path, filename="Goethe_A1_Wortliste.apkg", media_type="application/octet-stream")


# --- Goethe-Zertifikat A1 Schreiben Workshop Endpoints ---
class A1FormularCheckReq(BaseModel):
    exercise_id: str
    answers: Dict[str, str]


class A1EmailDiagnoseReq(BaseModel):
    text: str
    leitpunkte: Optional[List[str]] = None


@app.get("/api/a1/schreiben/teil1")
def get_a1_schreiben_teil1():
    import a1_writing_dict
    return a1_writing_dict.A1_SCHREIBEN_TEIL1


@app.post("/api/a1/schreiben/teil1/check")
def check_a1_schreiben_teil1(req: A1FormularCheckReq):
    import a1_writing_dict
    from writing_rules import check_a1_formular_answer

    ex_map = {ex["id"]: ex for ex in a1_writing_dict.A1_SCHREIBEN_TEIL1}
    ex = ex_map.get(req.exercise_id)
    if not ex:
        raise HTTPException(404, "填表题目未找到")

    results = {}
    score = 0
    total = len(ex["fields"])

    for fld in ex["fields"]:
        key = fld["key"]
        user_val = req.answers.get(key, "")
        chk = check_a1_formular_answer(user_val, fld["answer"], fld.get("aliases", []))
        chk["tip"] = fld.get("tip", "")
        chk["label"] = fld.get("label", "")
        if chk["correct"]:
            score += 1
        results[key] = chk

    return {
        "exercise_id": req.exercise_id,
        "score": score,
        "total": total,
        "all_correct": score == total,
        "results": results
    }


@app.get("/api/a1/schreiben/teil2")
def get_a1_schreiben_teil2():
    import a1_writing_dict
    return a1_writing_dict.A1_SCHREIBEN_TEIL2


@app.post("/api/a1/schreiben/teil2/diagnose")
def diagnose_a1_schreiben_teil2(req: A1EmailDiagnoseReq):
    from writing_rules import analyze_a1_email
    return analyze_a1_email(req.text[:2000], req.leitpunkte)



# --- Edge Neural TTS Audio Endpoints ---
class TTSReq(BaseModel):
    text: str
    voice: Optional[str] = "de-DE-KatjaNeural"
    rate: Optional[str] = "+0%"


# 朗读输入上限：局域网可达端点，防超大文本打满合成队列与磁盘缓存（场景是词/句级）
MAX_TTS_TEXT_LEN = 1000


async def generate_edge_tts_audio(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%") -> str:
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(400, "Text cannot be empty")
    if len(clean_text) > MAX_TTS_TEXT_LEN:
        raise HTTPException(400, f"朗读文本过长（最多 {MAX_TTS_TEXT_LEN} 字符）")

    cache_key = hashlib.sha256(f"{voice}_{rate}_{clean_text}".encode("utf-8")).hexdigest()
    cache_file = os.path.join(AUDIO_CACHE_DIR, f"{cache_key}.mp3")

    if os.path.exists(cache_file) and os.path.getsize(cache_file) > 100:
        return cache_file

    try:
        import edge_tts
        communicate = edge_tts.Communicate(clean_text, voice=voice, rate=rate)
        await communicate.save(cache_file)
    except ImportError:
        # Android/Chaquopy 没有 edge_tts 的 wheel（aiohttp 等依赖缺）→ 用 stdlib 版客户端
        # （edge_tts_mini 复刻同一 WebSocket+Sec-MS-GEC 协议，零依赖）
        import edge_tts_mini
        audio_data = await asyncio.to_thread(
            edge_tts_mini.synthesize, clean_text, voice, rate
        )
        with open(cache_file, "wb") as f:
            f.write(audio_data)
    except Exception as e:
        # Multi-provider pure-Python httpx fallback (accessible in mainland China)
        from urllib.parse import quote
        q = quote(clean_text[:250])
        candidate_urls = [
            f"https://dict.youdao.com/dictvoice?audio={q}&le=de",
            f"https://fanyi.baidu.com/gettts?lan=de&text={q}&spd=3&source=web",
            f"https://translate.google.com/translate_tts?ie=UTF-8&q={q}&tl=de&client=tw-ob"
        ]
        for tts_url in candidate_urls:
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(tts_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    if resp.status_code == 200 and len(resp.content) > 200:
                        with open(cache_file, "wb") as f:
                            f.write(resp.content)
                        prune_audio_cache()
                        return cache_file
            except Exception:
                continue
        raise HTTPException(500, f"TTS synthesis failed: {str(e)}")

    # 主路径（edge_tts 或 edge_tts_mini）成功：落地缓存后返回
    prune_audio_cache()
    return cache_file

_TTS_RATE_RE = re.compile(r"^[+-]\d+%$")

async def _serve_tts(text: str, voice: str, rate: str):
    """POST 与 GET 两个路由共享的 TTS 服务逻辑。"""
    if not _TTS_RATE_RE.match(rate or ""):
        raise HTTPException(status_code=400, detail="rate must look like '+0%', '-10%' or '+50%'")
    try:
        audio_path = await generate_edge_tts_audio(text, voice, rate)
        return FileResponse(audio_path, media_type="audio/mpeg", filename="speech.mp3")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"TTS synthesis failed: {str(e)}")

@app.post("/api/audio/tts")
async def get_audio_tts(req: TTSReq):
    return await _serve_tts(req.text, req.voice or "de-DE-KatjaNeural", req.rate or "+0%")

@app.get("/api/audio/tts")
async def audio_tts_get(text: str, voice: str = "de-DE-KatjaNeural", rate: str = "+0%"):
    """GET 版 TTS：供 <audio src="/api/audio/tts?text=..."> 直接用。
    与 POST 共享同一缓存池（cache key 仍为 sha256(f"{voice}_{rate}_{clean_text}")）。"""
    return await _serve_tts(text, voice, rate)

@app.get("/api/audio/cache")
def get_audio_cache():
    return get_cache_info(AUDIO_CACHE_DIR)

@app.post("/api/audio/cache/clear")
def clear_audio_cache():
    info = get_cache_info(AUDIO_CACHE_DIR)
    cleared_count = 0
    if os.path.exists(AUDIO_CACHE_DIR):
        for fname in os.listdir(AUDIO_CACHE_DIR):
            fpath = os.path.join(AUDIO_CACHE_DIR, fname)
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    cleared_count += 1
            except Exception:
                pass
    return {
        "status": "ok",
        "cleared_count": cleared_count,
        "freed_mb": info["total_size_mb"]
    }

# --- Reading Notes & AI Assist Endpoints ---
class ReadingNoteReq(BaseModel):
    sentence_id: Optional[int] = None
    selected_text: str
    color: Optional[str] = "yellow"
    note_content: Optional[str] = ""

@app.get("/api/articles/{article_id}/notes")
def list_article_notes(article_id: int):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/articles/{article_id}/notes")
def create_article_note(article_id: int, req: ReadingNoteReq):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO reading_notes (article_id, sentence_id, selected_text, color, note_content) VALUES (?, ?, ?, ?, ?)",
            (article_id, req.sentence_id, req.selected_text, req.color or "yellow", req.note_content or "")
        )
        return {"id": cur.lastrowid, "status": "ok"}

@app.delete("/api/notes/{note_id}")
def delete_article_note(note_id: int):
    with get_db() as conn:
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
    sentence: str
    selected_text: str

@app.post("/api/ai/note-assist")
async def note_assist(req: NoteAssistReq):
    key = get_effective_api_key()
    if not key:
        import logging
        logging.warning("[note-assist] API Key not set — returning stub response. Set in Settings.")
        return {
            "summary_zh": f"精读重点：{req.selected_text}",
            "key_points": ["请在右上角「⚙️ 设置」中配置 API Key 获取深度 AI 语法与搭配解析。"],
            "_stub": True
        }

    base_url = get_effective_api_base_url().rstrip('/')
    model = get_effective_api_model()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_NOTE_PROMPT},
                        {"role": "user", "content": f"整句: \"{req.sentence}\"\n划选部分: \"{req.selected_text}\""}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if getattr(resp, "status_code", 200) != 200:
                raise HTTPException(status_code=502, detail=f"AI 服务异常 ({getattr(resp, 'status_code', 500)})")
            try:
                data = resp.json()
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回非 JSON 响应")
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务响应格式异常")
            try:
                return json.loads(content)
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回内容非 JSON")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="AI 服务连接失败")

# --- Settings & Configuration API ---
class SettingsUpdate(BaseModel):
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    api_model: Optional[str] = None
    tts_voice: Optional[str] = None
    tts_rate: Optional[str] = None

@app.get("/api/settings")
def get_app_settings():
    key = get_effective_api_key()
    masked = ""
    if key:
        if len(key) > 8:
            masked = key[:4] + "•" * (len(key) - 8) + key[-4:]
        else:
            masked = "••••••••"
    return {
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "api_base_url": get_effective_api_base_url(),
        "api_model": get_effective_api_model(),
        "tts_voice": get_setting("TTS_VOICE", "de-DE-KatjaNeural"),
        "tts_rate": get_setting("TTS_RATE", "+0%"),
        "nlp_engine": NLP_ENGINE,
        "nlp_engine_detail": NLP_ENGINE_DETAIL
    }

@app.post("/api/settings")
def update_app_settings(settings: SettingsUpdate, request: Request):
    _require_localhost(request)
    if settings.api_key is not None and settings.api_key.strip() != "":
        set_setting("DEEPSEEK_API_KEY", settings.api_key.strip())
    if settings.api_base_url is not None and settings.api_base_url.strip() != "":
        set_setting("API_BASE_URL", settings.api_base_url.strip())
    if settings.api_model is not None and settings.api_model.strip() != "":
        set_setting("API_MODEL", settings.api_model.strip())
    if settings.tts_voice is not None and settings.tts_voice.strip() != "":
        set_setting("TTS_VOICE", settings.tts_voice.strip())
    if settings.tts_rate is not None and settings.tts_rate.strip() != "":
        set_setting("TTS_RATE", settings.tts_rate.strip())
    return {"success": True, "message": "偏好与 API 设置已保存！"}

@app.post("/api/settings/test-key")
async def test_api_key(settings: SettingsUpdate, request: Request):
    _require_localhost(request)
    key = settings.api_key.strip() if (settings.api_key and settings.api_key.strip()) else get_effective_api_key()
    if not key:
        return {"success": False, "error": "请先输入 API Key"}
    base_url = (settings.api_base_url.strip() if settings.api_base_url else get_effective_api_base_url()).rstrip('/')
    model = settings.api_model.strip() if settings.api_model else get_effective_api_model()

    import time
    start_t = time.time()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Sag 'OK'."}],
                    "max_tokens": 5
                }
            )
            latency = int((time.time() - start_t) * 1000)
            if resp.status_code == 200:
                return {"success": True, "latency_ms": latency, "message": f"连接成功！响应延迟: {latency}ms"}
            else:
                return {"success": False, "error": f"连接返回错误代码: {resp.status_code} ({resp.text[:100]})"}
    except Exception as e:
        return {"success": False, "error": f"连接失败: {str(e)}"}

# --- Study Guide Export (Markdown) ---
@app.get("/api/articles/{article_id}/export-guide")
def export_study_guide(article_id: int):
    with get_db() as conn:
        art = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        if not art:
            raise HTTPException(404, "Article not found")
        notes = conn.execute("SELECT * FROM reading_notes WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        vocab = conn.execute("SELECT * FROM vocab_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()
        grammar = conn.execute("SELECT * FROM grammar_cards WHERE article_id = ? ORDER BY id ASC", (article_id,)).fetchall()

    md = [f"# {art['title']} — DeLector 精读讲义\n"]
    md.append(f"> 导出日期: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 字符数: {len(art['raw_text'])}\n")

    if notes:
        md.append("## 📝 精读随笔与重点批注\n")
        for n in notes:
            md.append(f"- **高亮原句**: *{n['selected_text']}*")
            if n['note_content']:
                md.append(f"  - 💡 **随笔笔记**: {n['note_content']}")
        md.append("")

    if vocab:
        md.append("## 🗂️ 核心生词表\n")
        md.append("| 单词 | 原型 | 词性 | CEFR | 中文释义 | 原文语境 |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for v in vocab:
            md.append(f"| **{v['word']}** | {v['lemma']} | {v['pos']} | {v['cefr_level']} | {v['definition_zh']} | *{v['sentence_context']}* |")
        md.append("")

    if grammar:
        md.append("## 🎓 歌德考点深度解析\n")
        for g in grammar:
            md.append(f"### ✦ {g['grammar_name']} ({g['cefr_level']})")
            if g['rule_formula']:
                md.append(f"- **语法公式**: `{g['rule_formula']}`")
            md.append(f"- **解析**: {g['explanation_zh']}")
            md.append(f"- **例句**: *{g['sentence_context']}*\n")

    content = "\n".join(md)
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=study_guide_{article_id}.md"}
    )

# --- Backup & Restore Endpoints ---

@app.get("/api/backup/export")
def export_database_backup(request: Request):
    """原始导出端点，保留给脚本/桌面直连使用。

    UI 走 /prepare + /download —— 只有那条路径能带上 localStorage，
    也只有它在 Android WebView 里真的能下载（blob: 到不了 DownloadListener）。
    """
    _require_localhost(request)
    return build_backup_payload()


class PrepareBackupReq(BaseModel):
    local_storage: Dict[str, Any] = {}


@app.post("/api/backup/prepare")
def prepare_backup_download(req: PrepareBackupReq, request: Request):
    """前端提交 localStorage → 后端合成完整备份 → 返回一次性下载 token。

    为什么要两步：导航只能是 GET，所以 POST 的响应无法触发浏览器下载；
    而 Android WebView 只在「真 http URL + Content-Disposition」时才走原生下载桥。
    """
    _require_localhost(request)
    payload = build_backup_payload()
    payload["local_storage"] = req.local_storage or {}
    token = secrets.token_urlsafe(16)
    _pending_backup.update(
        token=token,
        payload=payload,
        filename=f"delector_backup_{datetime.now().strftime('%Y-%m-%d')}.json",
    )
    return {"token": token, "filename": _pending_backup["filename"]}


@app.get("/api/backup/download/{token}")
def download_prepared_backup(token: str, request: Request):
    _require_localhost(request)
    pending = _pending_backup["token"]
    if not pending or not secrets.compare_digest(token, pending):
        raise HTTPException(404, "备份链接已失效，请重新导出")
    payload, filename = _pending_backup["payload"], _pending_backup["filename"]
    _pending_backup.update(token=None, payload=None, filename=None)  # 单次有效
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Workbench backup (同理，Android WebView 对 blob: URL 静默失败) ────────

class WbBackupReq(BaseModel):
    filename: str = "workbench-backup.json"
    payload: Dict[str, Any] = {}


@app.post("/api/wb/backup/prepare")
def wb_prepare_backup(req: WbBackupReq, request: Request):
    _require_localhost(request)
    token = secrets.token_urlsafe(16)
    _pending_wb.update(token=token, payload=req.payload, filename=req.filename)
    return {"token": token, "filename": req.filename}


@app.get("/api/wb/backup/download/{token}")
def wb_download_backup(token: str, request: Request):
    _require_localhost(request)
    pending = _pending_wb["token"]
    if not pending or not secrets.compare_digest(token, pending):
        raise HTTPException(404, "备份链接已失效，请重新导出")
    payload, filename = _pending_wb["payload"], _pending_wb["filename"]
    _pending_wb.update(token=None, payload=None, filename=None)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


class RestoreReq(BaseModel):
    version: Optional[int] = 1
    articles: List[Dict[str, Any]] = []
    vocab_cards: List[Dict[str, Any]] = []
    grammar_cards: List[Dict[str, Any]] = []
    reading_notes: List[Dict[str, Any]] = []
    prep_saved: List[Dict[str, Any]] = []
    essays: List[Dict[str, Any]] = []
    essay_versions: List[Dict[str, Any]] = []
    # v1 备份没有以下字段，缺省为空即可被读入（向后兼容是硬要求：
    # 迁移用户手里拿的恰恰是 v3.9.1 导出的 v1 文件）
    app_settings: List[Dict[str, Any]] = []
    study_log: List[Dict[str, Any]] = []
    quiz_log: List[Dict[str, Any]] = []
    daily_summary: List[Dict[str, Any]] = []
    local_storage: Dict[str, Any] = {}


@app.post("/api/backup/restore")
def restore_database_backup(req: RestoreReq, request: Request):
    """真覆盖还原：事务内清库再灌，而非按 id merge。

    为什么不是 merge：merge 需要重新映射 article_id 外键
    （vocab_cards / grammar_cards / reading_notes 都引用它），是一整套 id
    重映射逻辑与相应的正确性风险；而「换机/重装后还原」场景的目标库一定是空的，
    两者行为一致。按钮标签写的是「还原备份」，真覆盖才符合字面语义。
    """
    _require_localhost(request)
    payload = req.model_dump() if hasattr(req, "model_dump") else req.dict()

    with _db_snapshot_guard():
        conn = get_db()
        try:
            with conn:
                _replace_tables(conn, _BACKUP_TABLES, payload)
                # app_settings 的覆盖**只作用于白名单键**：整表 DELETE 会连带
                # 抹掉 DEEPSEEK_API_KEY（它从不进备份，抹了就再也灌不回来）。
                conn.executemany(
                    "DELETE FROM app_settings WHERE key = ?",
                    [(k,) for k in BACKUP_SETTINGS_WHITELIST],
                )
                conn.executemany(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?)",
                    [(s["key"], s.get("value"))
                     for s in (payload.get("app_settings") or [])
                     if s.get("key") in BACKUP_SETTINGS_WHITELIST],
                )
        finally:
            conn.close()

        pconn = get_progress_db()
        try:
            with pconn:
                _replace_tables(pconn, _PROGRESS_TABLES, payload)
        finally:
            pconn.close()

    return {"status": "ok", "message": "全量备份恢复成功"}




# ── v3.0 / v3.8: FSRS Spaced Repetition Review & Cloze Exercise Engine ────────

class CardReviewReq(BaseModel):
    grade: int  # 1: Forgot, 2: Hard, 3: Good, 4: Easy
    card_type: Optional[str] = None

@app.post("/api/cards/{card_type}/{card_id}/review")
def review_card_sm2(card_type: str, card_id: int, req: CardReviewReq):
    if card_type not in ("vocab", "grammar"):
        raise HTTPException(400, "card_type must be 'vocab' or 'grammar'")
    tbl = "vocab_cards" if card_type == "vocab" else "grammar_cards"
    with get_db() as conn:
        row = conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (card_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Card {card_id} not found")

        rep = row["repetition_count"] if "repetition_count" in row.keys() and row["repetition_count"] is not None else 0
        interval = row["interval_days"] if "interval_days" in row.keys() and row["interval_days"] is not None else 1
        ef = row["ease_factor"] if "ease_factor" in row.keys() and row["ease_factor"] is not None else 2.5

        new_rep, new_interval, new_ef, due_date, next_intervals = calculate_fsrs(req.grade, rep, interval, ef)

        is_correct = req.grade >= 2
        correct_incr = 1 if is_correct else 0
        wrong_incr = 1 if not is_correct else 0

        conn.execute(f"""
            UPDATE {tbl}
            SET repetition_count = ?, interval_days = ?, ease_factor = ?, due_date = ?,
                correct_count = correct_count + ?, wrong_count = wrong_count + ?
            WHERE id = ?
        """, (new_rep, new_interval, new_ef, due_date, correct_incr, wrong_incr, card_id))

        updated = dict(conn.execute(f"SELECT * FROM {tbl} WHERE id = ?", (card_id,)).fetchone())
        updated["next_intervals"] = next_intervals

    with get_progress_db() as pconn:
        pconn.execute(
            "INSERT INTO quiz_log (card_id, card_type, mode, correct) VALUES (?, ?, ?, ?)",
            (card_id, card_type, "fsrs_review", 1 if is_correct else 0)
        )
    log_study_event("quiz_session", card_id, f"fsrs:{card_type}:{card_id}")
    return updated

@app.get("/api/cards/due")
def get_due_cards():
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as conn:
        v = [dict(r) for r in conn.execute(
            "SELECT * FROM vocab_cards WHERE mastered = 0 AND (due_date IS NULL OR due_date <= ?) ORDER BY wrong_count DESC, id ASC",
            (today,)
        ).fetchall()]
        g = [dict(r) for r in conn.execute(
            "SELECT * FROM grammar_cards WHERE mastered = 0 AND (due_date IS NULL OR due_date <= ?) ORDER BY wrong_count DESC, id ASC",
            (today,)
        ).fetchall()]
        for card in v + g:
            card["next_intervals"] = get_fsrs_next_intervals(
                card.get("repetition_count") or 0,
                card.get("interval_days") or 1,
                card.get("ease_factor") or 2.5
            )
        return {
            "due_vocab": v,
            "due_grammar": g,
            "due_count": len(v) + len(g),
            "today": today
        }

def generate_cloze_exercise(text: str, mode: str = "grammar", article_id: Optional[int] = None) -> Dict[str, Any]:
    if nlp is None:
        # Simple pure-Python cloze fallback
        words = re.findall(r'\w+|[^\w\s]+|\s+', text, re.UNICODE)
        items = []
        tokens_output = []
        blank_counter = 0
        for w in words:
            if w.isalpha() and len(w) >= 4 and blank_counter < 5 and blank_counter % 2 == 0:
                first_letter = w[0]
                items.append({
                    "index": blank_counter,
                    "original": w,
                    "first_letter": first_letter,
                    "lemma": w.lower(),
                    "pos": "NOUN" if w[0].isupper() else "VERB",
                    "hint": f"首字母: {first_letter}...",
                    "type": mode,
                    "sent_idx": 0
                })
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
            "items": items
        }
    doc = nlp(text)
    items = []
    tokens_output = []
    blank_counter = 0

    if mode == "grammar":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                is_grammar_target = (
                    token.pos_ in ("ADP", "SCONJ", "CCONJ") or
                    (token.pos_ == "AUX" and token.text.lower() in ("wurde", "worden", "werden", "wäre", "hätte", "könnte", "müsste", "sollte")) or
                    (token.pos_ == "ADJ" and len(token.text) > 3)
                )
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_grammar_target and len(sent_blanks) < 2 and len(token.text) >= 2:
                    first_letter = token.text[0]
                    items.append({
                        "index": blank_counter,
                        "original": token.text,
                        "first_letter": first_letter,
                        "lemma": token.lemma_,
                        "pos": token.pos_,
                        "hint": f"首字母: {first_letter}...",
                        "type": "grammar",
                        "sent_idx": sent_idx
                    })
                    tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                    blank_counter += 1
                else:
                    tokens_output.append(token.text_with_ws)

    elif mode == "vocab":
        for sent_idx, sent in enumerate(doc.sents):
            for token in sent:
                lvl = get_cefr_level(token.lemma_)
                is_vocab_target = token.pos_ in ("NOUN", "VERB") and lvl in ("A2", "B1", "B2", "C1") and len(token.text) >= 3
                sent_blanks = [it for it in items if it.get("sent_idx") == sent_idx]
                if is_vocab_target and len(sent_blanks) < 2:
                    first_letter = token.text[0]
                    items.append({
                        "index": blank_counter,
                        "original": token.text,
                        "first_letter": first_letter,
                        "lemma": token.lemma_,
                        "pos": token.pos_,
                        "hint": f"首字母: {first_letter}... ({token.lemma_})",
                        "type": "vocab",
                        "sent_idx": sent_idx
                    })
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
                        items.append({
                            "index": blank_counter,
                            "original": token.text,
                            "prefix": prefix,
                            "suffix": suffix,
                            "first_letter": prefix,
                            "hint": f"词首: {prefix}...",
                            "type": "ctest",
                            "sent_idx": sent_idx
                        })
                        tokens_output.append(f"{prefix}[[BLANK_{blank_counter}]]{token.whitespace_}")
                        blank_counter += 1
                        continue
                tokens_output.append(token.text_with_ws)

    if len(items) == 0:
        for token in doc:
            if token.is_alpha and len(token.text) >= 4 and blank_counter < 3:
                first_letter = token.text[0]
                items.append({
                    "index": blank_counter,
                    "original": token.text,
                    "first_letter": first_letter,
                    "lemma": token.lemma_,
                    "hint": f"首字母: {first_letter}...",
                    "type": mode,
                    "sent_idx": 0
                })
                tokens_output.append(f"[[BLANK_{blank_counter}]]{token.whitespace_}")
                blank_counter += 1
            else:
                tokens_output.append(token.text_with_ws)

    masked_text = "".join(tokens_output)
    return {
        "mode": mode,
        "items": items,
        "total_blanks": len(items),
        "masked_text": masked_text
    }

class ClozeGenReq(BaseModel):
    mode: Optional[str] = "grammar"

@app.post("/api/articles/{article_id}/exercise/cloze")
def get_article_cloze_exercise(article_id: int, req: ClozeGenReq):
    with get_db() as conn:
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

@app.post("/api/exercise/cloze/evaluate")
def evaluate_cloze_exercise(req: ClozeEvalReq):
    with get_db() as conn:
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
            is_correct = (user_ans.lower() == expected.lower())

        if is_correct:
            correct_count += 1

        results.append({
            "index": item["index"],
            "correct": is_correct,
            "user_answer": user_ans,
            "expected": expected,
            "hint": item.get("hint", ""),
            "type": item.get("type", "grammar")
        })

    total = len(items)
    accuracy_pct = round((correct_count / total * 100)) if total > 0 else 0

    log_study_event("quiz_session", req.article_id, f"cloze:{req.mode}:{req.article_id}", minutes=3)

    return {
        "score": correct_count,
        "total": total,
        "accuracy_pct": accuracy_pct,
        "results": results
    }

class SyntaxAnalyzeReq(BaseModel):
    text: str

@app.post("/api/syntax/analyze")
def api_syntax_analyze(req: SyntaxAnalyzeReq):
    return analyze_syntax_tree(req.text)

# --- Writing Desk (Schreibwerkstatt) Endpoints ---

SYSTEM_WRITING_POLISH_PROMPT = """你是一位精通德语学术写作与德福/歌德高级写作评分标准的资深德语教学专家。
请对用户提交的德语作文/文本进行全面的语法纠错、用词地道化润色与结构优化。
请尽量逐句润色，保持句子的结构与出现顺序，不要合并或拆分句子，除非确实必要。
请严格输出如下 JSON 格式：
{
  "corrected_text": "润色纠错后的完整德语文本",
  "notes_zh": [
    "修改点说明1",
    "修改点说明2"
  ],
  "error_count": 2
}
不要输出除 JSON 以外的任何文字。"""


def _get_writer_nlp():
    try:
        return nlp
    except Exception:
        return None


@app.post("/api/writing/analyze")
def api_writing_analyze(req: WritingAnalyzeReq):
    from writing_rules import analyze_essay_text
    return analyze_essay_text(req.text[:2000], _get_writer_nlp())


@app.post("/api/essays")
def create_essay(req: EssayCreateReq):
    from writing_rules import analyze_essay_text
    a = analyze_essay_text(req.content[:5000], _get_writer_nlp())
    cefr = a.get("cefr", {}).get("recommended_level")
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO essays (title, content, analysis_json, cefr_level, error_count, sentence_count) VALUES (?, ?, ?, ?, ?, ?)",
            (req.title, req.content, json.dumps(a, ensure_ascii=False), cefr, a["error_count"], len(a["sentences"]))
        )
        eid = cur.lastrowid
    return {"id": eid, "title": req.title, "content": req.content, "analysis_json": a, "error_count": a["error_count"]}


@app.get("/api/essays")
def list_essays():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, cefr_level, error_count, sentence_count, created_at, updated_at FROM essays ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/essays/{essay_id}")
def get_essay(essay_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    data = dict(row)
    if isinstance(data.get("analysis_json"), str):
        try:
            data["analysis_json"] = json.loads(data["analysis_json"])
        except Exception:
            pass
    return data


@app.put("/api/essays/{essay_id}")
def update_essay(essay_id: int, req: EssayUpdateReq):
    from writing_rules import analyze_essay_text
    with get_db() as conn:
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
            (title, content, json.dumps(a, ensure_ascii=False),
             a.get("cefr", {}).get("recommended_level"), a["error_count"],
             len(a["sentences"]), now_str, essay_id)
        )
    return {"id": essay_id, "title": title, "content": content, "analysis_json": a, "error_count": a["error_count"]}


@app.delete("/api/essays/{essay_id}")
def delete_essay(essay_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        conn.execute("DELETE FROM essay_versions WHERE essay_id = ?", (essay_id,))
        conn.execute("DELETE FROM essays WHERE id = ?", (essay_id,))
    return {"status": "ok"}


@app.post("/api/writing/cards")
def save_writing_card(req: WritingCardReq):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (req.essay_id,)).fetchone()
    if not row:
        raise HTTPException(404, "essay not found")
    raw_analysis = row["analysis_json"]
    a = json.loads(raw_analysis) if isinstance(raw_analysis, str) else raw_analysis
    sentences = a.get("sentences", [])
    if req.sentence_id < 0 or req.sentence_id >= len(sentences):
        raise HTTPException(400, "sentence_id 越界")
    sent = sentences[req.sentence_id]
    spans = sent.get("spans", [])
    if req.span_index < 0 or req.span_index >= len(spans):
        raise HTTPException(400, "span_index 越界")
    sp = spans[req.span_index]
    sentence_text = sent.get("text", "")
    card = GrammarCardReq(
        article_id=None,
        sentence_context=sentence_text,
        grammar_name=f"写作润色 · {sp['error_type']}",
        cefr_level=row["cefr_level"] or "B1",
        explanation_zh=sp["explanation_zh"],
        rule_formula=sp["corrected_form"],
        corrected_form=sp["corrected_form"],
        error_type=sp["error_type"],
    )
    return add_grammar_card(card)


async def _ai_polish_call(text: str) -> Tuple[str, List[str], int]:
    key = get_effective_api_key()
    if not key:
        import logging
        logging.warning("[writing/ai-polish] API Key not set — returning stub response.")
        return text, ["请在设置中配置 DeepSeek API Key 后使用 AI 润色功能"], 0

    base_url = get_effective_api_base_url().rstrip('/')
    model = get_effective_api_model()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_WRITING_POLISH_PROMPT},
                        {"role": "user", "content": f"德语文本:\n{text}"}
                    ],
                    "response_format": {"type": "json_object"}
                }
            )
            if getattr(resp, "status_code", 200) != 200:
                raise HTTPException(status_code=502, detail=f"AI 服务异常 ({getattr(resp, 'status_code', 500)})")
            try:
                data = resp.json()
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回非 JSON 响应")
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务响应格式异常")
            try:
                parsed = json.loads(content)
            except Exception:
                raise HTTPException(status_code=502, detail="AI 服务返回内容非 JSON")
            corrected_text = parsed.get("corrected_text", text)
            notes_zh = parsed.get("notes_zh", [])
            error_count = parsed.get("error_count", len(notes_zh))
            return corrected_text, notes_zh, error_count
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.error(f"[writing/ai-polish] DeepSeek API error: {e}")
        raise HTTPException(status_code=502, detail="AI 服务连接失败")


@app.post("/api/writing/ai-polish")
async def api_writing_ai_polish(req: AIPolishReq):
    text = req.text[:2000]
    corrected_text, notes_zh, error_count = await _ai_polish_call(text)
    return {
        "status": "ok",
        "result": {
            "corrected_text": corrected_text,
            "notes_zh": notes_zh,
            "error_count": error_count,
        }
    }


@app.post("/api/writing/ai-polish/diff")
async def api_writing_ai_polish_diff(req: AIPolishReq):
    from essay_diff import diff_sentences
    text = req.text[:2000]
    corrected_text, notes_zh, error_count = await _ai_polish_call(text)
    hunks = diff_sentences(text, corrected_text)
    return {
        "status": "ok",
        "result": {
            "original": text,
            "corrected": corrected_text,
            "hunks": hunks,
            "notes_zh": notes_zh,
            "error_count": error_count,
        }
    }


@app.post("/api/essays/{essay_id}/versions")
def save_essay_version(essay_id: int, req: EssayVersionCreateReq):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        msg = req.message.strip() if (req.message and req.message.strip()) else "手动保存"
        cur = conn.execute(
            "INSERT INTO essay_versions (essay_id, content, analysis_json, message) "
            "VALUES (?, ?, ?, ?)",
            (essay_id, row["content"], row["analysis_json"], msg)
        )
        version_id = cur.lastrowid
        created_row = conn.execute("SELECT created_at FROM essay_versions WHERE id = ?", (version_id,)).fetchone()
        created_at = created_row["created_at"] if created_row else datetime.utcnow().isoformat()
    return {"version_id": version_id, "message": msg, "created_at": created_at}


@app.get("/api/essays/{essay_id}/versions")
def list_essay_versions(essay_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not row:
            raise HTTPException(404, "essay not found")
        rows = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE essay_id = ? ORDER BY id DESC",
            (essay_id,)
        ).fetchall()
        result = []
        for r in rows:
            raw_a = r["analysis_json"]
            try:
                a = json.loads(raw_a) if isinstance(raw_a, str) else raw_a
                err_count = a.get("error_count", 0) if isinstance(a, dict) else 0
            except Exception:
                err_count = 0
            result.append({
                "id": r["id"],
                "essay_id": r["essay_id"],
                "message": r["message"],
                "created_at": r["created_at"],
                "error_count": err_count,
            })
    return result


@app.get("/api/essays/{essay_id}/versions/{version_id}")
def get_essay_version(essay_id: int, version_id: int):
    with get_db() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id, essay_id, content, message, created_at, analysis_json "
            "FROM essay_versions WHERE id = ? AND essay_id = ?",
            (version_id, essay_id)
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


@app.delete("/api/essays/{essay_id}/versions/{version_id}")
def delete_essay_version(essay_id: int, version_id: int):
    with get_db() as conn:
        essay = conn.execute("SELECT id FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        v = conn.execute(
            "SELECT id FROM essay_versions WHERE id = ? AND essay_id = ?",
            (version_id, essay_id)
        ).fetchone()
        if not v:
            raise HTTPException(404, "version not found")
        conn.execute(
            "DELETE FROM essay_versions WHERE id = ? AND essay_id = ?",
            (version_id, essay_id)
        )
    return {"status": "ok", "deleted_version_id": version_id}


@app.post("/api/essays/{essay_id}/restore")
def restore_essay_version(essay_id: int, req: EssayRestoreReq):
    from writing_rules import analyze_essay_text
    with get_db() as conn:
        essay = conn.execute("SELECT * FROM essays WHERE id = ?", (essay_id,)).fetchone()
        if not essay:
            raise HTTPException(404, "essay not found")
        version = conn.execute(
            "SELECT * FROM essay_versions WHERE id = ? AND essay_id = ?",
            (req.version_id, essay_id)
        ).fetchone()
        if not version:
            raise HTTPException(404, "version not found")

        checkpoint_version_id = None
        if version["content"] != essay["content"]:
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) "
                "VALUES (?, ?, ?, ?)",
                (essay_id, essay["content"], essay["analysis_json"], f"恢复到版本 {req.version_id} 之前")
            )
            checkpoint_version_id = cur.lastrowid
            a = analyze_essay_text(version["content"][:5000], _get_writer_nlp())
            now_str = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE essays SET content = ?, analysis_json = ?, cefr_level = ?, "
                "error_count = ?, sentence_count = ?, updated_at = ? WHERE id = ?",
                (version["content"], json.dumps(a, ensure_ascii=False),
                 a.get("cefr", {}).get("recommended_level"), a["error_count"],
                 len(a["sentences"]), now_str, essay_id)
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


@app.post("/api/writing/apply")
def api_writing_apply(req: WritingApplyReq):
    from essay_diff import diff_sentences, merge_sentences
    from writing_rules import analyze_essay_text

    hunks = diff_sentences(req.original_text, req.corrected_text)
    if any(idx < 0 or idx >= len(hunks) for idx in req.accepted_indices):
        raise HTTPException(400, "accepted_indices 越界")

    accepted = [i in set(req.accepted_indices) for i in range(len(hunks))]
    merged = merge_sentences(req.original_text, req.corrected_text, accepted)

    with get_db() as conn:
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
                (row["title"], merged, json.dumps(a, ensure_ascii=False),
                 a.get("cefr", {}).get("recommended_level"), a["error_count"],
                 len(a["sentences"]), now_str, req.essay_id)
            )
            msg = f"AI 润色 · 接受 {len(req.accepted_indices)}/{len(hunks)} 处"
            cur = conn.execute(
                "INSERT INTO essay_versions (essay_id, content, analysis_json, message) "
                "VALUES (?, ?, ?, ?)",
                (req.essay_id, merged, json.dumps(a, ensure_ascii=False), msg)
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


# --- LAN WebRTC Sync SDP Cache & Endpoints ---
MAX_SYNC_CACHE_ENTRIES = 50
MAX_SDP_PAYLOAD_BYTES = 32 * 1024
_sync_sdp_cache: Dict[str, Dict[str, Any]] = {}


def _cleanup_sync_cache() -> None:
    now = time.time()
    expired = [k for k, v in _sync_sdp_cache.items() if now - v.get("ts", 0) > 300]
    for k in expired:
        _sync_sdp_cache.pop(k, None)
    # FIFO 容量限制：当条目数超标时淘汰最老的条目
    while len(_sync_sdp_cache) >= MAX_SYNC_CACHE_ENTRIES:
        oldest_key = min(_sync_sdp_cache.keys(), key=lambda k: _sync_sdp_cache[k].get("ts", 0))
        _sync_sdp_cache.pop(oldest_key, None)


class SyncStoreReq(BaseModel):
    sdp: Dict[str, Any]
    role: str = "offer"


@app.post("/api/wb/sync/store")
def sync_store_sdp(req: SyncStoreReq):
    raw_json = json.dumps(req.sdp)
    if len(raw_json.encode("utf-8")) > MAX_SDP_PAYLOAD_BYTES:
        raise HTTPException(400, "SDP payload 超过最大体积限制 (32KB)")
    _cleanup_sync_cache()
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    _sync_sdp_cache[code] = {
        "sdp": req.sdp,
        "ts": time.time(),
        "role": req.role,
    }
    return {"code": code}


@app.get("/api/wb/sync/fetch/{code}")
def sync_fetch_sdp(code: str):
    _cleanup_sync_cache()
    key = code.strip().upper()
    entry = _sync_sdp_cache.pop(key, None)
    if not entry:
        raise HTTPException(404, "短码无效或已过期（5 分钟有效）")
    return {"sdp": entry["sdp"], "role": entry["role"]}


# Mount Static UI (Catch-all must be at the very end)
STATIC_DIR = os.environ.get("STATIC_DIR")
if not STATIC_DIR or not os.path.exists(STATIC_DIR):
    for candidate in [
        os.path.join(DATA_DIR, "static"),
        os.path.join(os.path.dirname(__file__), "static"),
        os.path.join(os.getcwd(), "static"),
        "static"
    ]:
        if os.path.exists(candidate) and os.path.isdir(candidate):
            STATIC_DIR = candidate
            break

if STATIC_DIR and os.path.exists(STATIC_DIR):
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
