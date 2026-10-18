# -*- coding: utf-8 -*-
"""主路由：精简残余路由层（ADR-0008 Phase 1 Task 4 / C5 解耦）。

各分域路由已全部拆分为独立路由模块：
-  (设置与 API Key 探测)
-  (备份与同步状态)
-  (生词卡、语法卡、FSRS 算法调度与复习打卡)
-  (Edge Neural TTS 音频合成与缓存清理)
-  (文章摄入、阅读、批注、讲义导出与完形填空)
-  (写作分析、AI 润色循环、作文与版本链)

本模块仅保留残余的跨域通用能力：
- 词法与语法考点查询 ()
- 介词矩阵与固定搭配 ()
- 句法树与语料库统计 ()
- 真实数据库健康探针 ()

为了保持历史单测与依赖方兼容，本模块透明再导出已抽取的请求模型与公共函数。
"""

# mypy: disable-error-code="misc,untyped-decorator"

import json
from typing import Any, Dict, List, Optional

import httpx as httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel

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
    upsert_corpus_syntax_stats,
)
from delector.core.lexicon import lookup_core_vocab
from delector.core.security import (
    fetch_remote_html as fetch_remote_html,
)
from delector.core.security import (
    is_safe_public_url as is_safe_public_url,
)
from delector.core.version import APP_VERSION
from delector.nlp_engine.linguistics import (
    build_prep_matrix,
    lookup_irregular_verb,
    lookup_linguistics_ext,
    lookup_prep_collocations,
    split_komposita,
)
from delector.nlp_engine.processor import (
    SYSTEM_GRAMMAR_PROMPT,
    get_cefr_level,
)
from delector.nlp_engine.processor import (
    process_german_text as process_german_text,
)
from delector.nlp_engine.syntax_tree import analyze_syntax_tree

# ── Compatibility Re-exports for Domain Routers ──────────────────────────────
from delector.routes.articles import (
    ARTICLES_LIST_DEFAULT_LIMIT as ARTICLES_LIST_DEFAULT_LIMIT,
)
from delector.routes.articles import (
    ClozeEvalReq as ClozeEvalReq,
)
from delector.routes.articles import (
    ClozeGenReq as ClozeGenReq,
)
from delector.routes.articles import (
    IngestReq as IngestReq,
)
from delector.routes.articles import (
    IngestUrlReq as IngestUrlReq,
)
from delector.routes.articles import (
    NoteAssistReq as NoteAssistReq,
)
from delector.routes.articles import (
    ReadingNoteReq as ReadingNoteReq,
)
from delector.routes.articles import (
    delete_article as delete_article,
)
from delector.routes.articles import (
    generate_cloze_exercise as generate_cloze_exercise,
)
from delector.routes.articles import (
    get_article as get_article,
)
from delector.routes.articles import (
    ingest as ingest,
)
from delector.routes.articles import (
    ingest_from_url as ingest_from_url,
)
from delector.routes.articles import (
    list_articles as list_articles,
)
from delector.routes.audio import (
    _TTS_CONCURRENCY_LIMIT as _TTS_CONCURRENCY_LIMIT,
)
from delector.routes.audio import (
    _TTS_SEMAPHORE as _TTS_SEMAPHORE,
)
from delector.routes.audio import (
    generate_edge_tts_audio as generate_edge_tts_audio,
)
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
from delector.routes.writing import (
    _LETTER_FORMAT_RULE_PREFIX as _LETTER_FORMAT_RULE_PREFIX,
)
from delector.routes.writing import (
    POLISH_PROSE_SYSTEM_PROMPT as POLISH_PROSE_SYSTEM_PROMPT,
)
from delector.routes.writing import (
    REASON_NO_API_KEY as REASON_NO_API_KEY,
)
from delector.routes.writing import (
    AIPolishReq as AIPolishReq,
)
from delector.routes.writing import (
    EssayCreateReq as EssayCreateReq,
)
from delector.routes.writing import (
    EssayRestoreReq as EssayRestoreReq,
)
from delector.routes.writing import (
    EssayUpdateReq as EssayUpdateReq,
)
from delector.routes.writing import (
    EssayVersionCreateReq as EssayVersionCreateReq,
)
from delector.routes.writing import (
    WritingAnalyzeReq as WritingAnalyzeReq,
)
from delector.routes.writing import (
    WritingApplyReq as WritingApplyReq,
)
from delector.routes.writing import (
    WritingCardReq as WritingCardReq,
)
from delector.routes.writing import (
    _JudgeRecorder as _JudgeRecorder,
)
from delector.routes.writing import (
    _make_judge as _make_judge,
)
from delector.routes.writing import (
    _polish_diff_payload as _polish_diff_payload,
)
from delector.routes.writing import (
    _polish_event_stream as _polish_event_stream,
)
from delector.routes.writing import (
    _polish_payload as _polish_payload,
)
from delector.routes.writing import (
    _polish_violations_of as _polish_violations_of,
)
from delector.routes.writing import (
    _PolishReplyRecorder as _PolishReplyRecorder,
)
from delector.routes.writing import (
    _run_polish as _run_polish,
)
from delector.routes.writing import (
    _sse_frame as _sse_frame,
)
from delector.routes.writing import (
    _text_kind as _text_kind,
)
from delector.routes.writing import (
    api_writing_ai_polish as api_writing_ai_polish,
)
from delector.routes.writing import (
    pick_system_prompt as pick_system_prompt,
)
from delector.routes.writing import (
    violations_for as violations_for,
)
from delector.services import llm_client

router = APIRouter()


class GrammarLookupReq(BaseModel):
    sentence: str
    target_phrase: str


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

class SyntaxAnalyzeReq(BaseModel):
    text: str


@router.post("/api/syntax/analyze")
def api_syntax_analyze(req: SyntaxAnalyzeReq) -> Any:
    return analyze_syntax_tree(req.text)

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
