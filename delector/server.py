import os
import ipaddress
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

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
from delector.database import (
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
    get_wb_state,
    save_wb_state,
    get_wb_sync_key,
    regenerate_wb_sync_key,
    get_effective_api_key,
    get_effective_api_base_url,
    get_effective_api_model,
    PRESET_ARTICLES,
    ingest_article,
    seed_preset_articles,
    VOCAB_MODEL,
    GRAMMAR_MODEL,
    export_anki_deck,
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
    BACKUP_TOKEN_TTL_SEC,
    _issue_pending,
    _take_pending,
    _db_snapshot_guard,
    _replace_tables,
    migrate_a1_records_to_exam_trials,
    get_prep_saved,
    add_prep_saved,
    upsert_corpus_syntax_stats,
    get_all_corpus_syntax_stats,
)

# --- 2. NLP & CEFR Tagging（re-export：handler 搬走后 server 自身不再消费）---
from delector.nlp_engine.processor import (
    nlp,
    NLP_ENGINE,
    NLP_ENGINE_DETAIL,
    CEFR_DICT,
    get_cefr_level,
    process_german_text,
    SYSTEM_GRAMMAR_PROMPT,
)

# --- 3. Security, SSRF & Feed Utilities（同上，纯 re-export）---
from delector.security import (
    _resolve_ssrf_targets,
    _IETF_PROTOCOL_ASSIGNMENTS,
    _IPV6_DENY_PREFIXES,
    _is_blocked_addr,
    is_safe_public_url,
    clean_html_to_article,
    MAX_REDIRECT_HOPS,
    MAX_HTML_BYTES,
    fetch_remote_html,
    PRESET_FEEDS,
    parse_rss_feed,
)

# ── 附件下载响应头 ────────────────────────────────────────────────────────────
# 实现在 delector/utils.py（Phase 1 Task 1 抽走，用于打破 routes/a1 → server 的
# 反向依赖）。此处 import 仅为保留 `delector.server._attachment_headers` 既有引用面。
from .utils import _attachment_headers, _NO_STORE_HEADERS

__all__ = [
    "nlp",
    "NLP_ENGINE",
    "NLP_ENGINE_DETAIL",
    "CEFR_DICT",
    "get_cefr_level",
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
    "get_wb_state",
    "save_wb_state",
    "get_wb_sync_key",
    "regenerate_wb_sync_key",
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
    "BACKUP_TOKEN_TTL_SEC",
    "_issue_pending",
    "_take_pending",
    "_db_snapshot_guard",
    "_replace_tables",
    "migrate_a1_records_to_exam_trials",
    "get_prep_saved",
    "add_prep_saved",
    "upsert_corpus_syntax_stats",
    "get_all_corpus_syntax_stats",
    "_resolve_ssrf_targets",
    "_IETF_PROTOCOL_ASSIGNMENTS",
    "_IPV6_DENY_PREFIXES",
    "_attachment_headers",
    "_NO_STORE_HEADERS",
    "_is_blocked_addr",
    "is_safe_public_url",
    "clean_html_to_article",
    "MAX_REDIRECT_HOPS",
    "MAX_HTML_BYTES",
    "fetch_remote_html",
    "PRESET_FEEDS",
    "parse_rss_feed",
    "_sync_sdp_cache",
    "MAX_SYNC_CACHE_ENTRIES",
]

# --- 4. 路由层 ---
# 注册入口只有 register_routes 一个：新增/搬迁路由模块只改 delector/routes/__init__.py，
# 本文件不应当再出现 include_router。
from delector.routes import MAX_SYNC_CACHE_ENTRIES, _sync_sdp_cache, register_routes

# --- 5. 中间件：前端资源 no-cache ---
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

# 注册走 create_app() 里的 app.middleware("http")(...)：app 是工厂产物，模块级没有
# 可装饰的对象。
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


# ── 局域网 CORS（Stage A：配对后手机 APP WebView 跨域访问需 ACAO 反射）────
# 只对「回环 / 私有网段」Origin 反射；公网 Origin 不加头 → 浏览器同源策略仍会
# 拦下响应，恶意网页读不到 wb 镜像。无 Origin 头的流量（本机/同源/存量用例）
# 不经由这里，行为零变化（lan_client 若不带 Origin 也不受影响）。

_WB_CORS_EXACT_PATHS = {"/api/wb/state", "/api/wb/state/key"}
_WB_CORS_PREFIXES = ("/api/wb/sync/", "/api/wb/rtc/")
_WB_CORS_ALLOW_HEADERS = "Content-Type, X-WB-Key"
# store / rtc 信令是 POST：缺 POST 会让跨域浏览器在预检阶段就被拒（回归）。
_WB_CORS_ALLOW_METHODS = "GET, PUT, POST, OPTIONS"


def _is_private_origin(origin: str) -> bool:
    """Origin 头的 host 属回环 / 私有网段才返回 True（否则不反射 ACAO）。"""
    if not origin:
        return False
    try:
        host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


# 注册走 create_app() 里的 app.middleware("http")(...)：app 是工厂产物，模块级没有
# 可装饰的对象。
async def _wb_sync_cors(request: Request, call_next):
    path = request.url.path
    origin = request.headers.get("Origin", "")
    is_wb_path = path in _WB_CORS_EXACT_PATHS or path.startswith(_WB_CORS_PREFIXES)
    if not is_wb_path or not origin:
        return await call_next(request)  # 非 wb 路径 / 无 Origin（本机/同源/存量用例）：行为零变化
    if request.method == "OPTIONS":
        # 浏览器预检：私有/回环 Origin 短路放行（不落入业务路由）；
        # 公共 Origin 显式 403 且不给 ACAO，浏览器判跨域失败（回归：此前漏到 405）。
        if not _is_private_origin(origin):
            return Response(status_code=403)
        return Response(status_code=200, headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": _WB_CORS_ALLOW_METHODS,
            "Access-Control-Allow-Headers": _WB_CORS_ALLOW_HEADERS,
            "Access-Control-Max-Age": "600",
        })
    if not _is_private_origin(origin):
        return await call_next(request)  # 公共 Origin：原样转发，不注入 ACAO
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response


# --- 6. 静态资源目录 ---
STATIC_DIR = os.environ.get("STATIC_DIR")
if not STATIC_DIR or not os.path.exists(STATIC_DIR):
    for candidate in [
        os.path.join(DATA_DIR, "static"),
        # 本模块在 delector/ 包内：dirname(__file__) 是包目录不是仓库根。
        # 回指一级才等价于打包前"仓库根/static"。首个候选 DATA_DIR/static
        # 在桌面（_internal/static）与 Android（filesDir/static）上通常已命中，
        # 这一级是 DATA_DIR 被外部改走时的兜底，别删。
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "static"),
        os.path.join(os.getcwd(), "static"),
        "static"
    ]:
        if os.path.exists(candidate) and os.path.isdir(candidate):
            STATIC_DIR = candidate
            break


# --- 7. 应用工厂 ---
def create_app() -> FastAPI:
    """装配一个完整的 DeLector app。

    要工厂而不是模块级 `app = FastAPI()` 的理由：init_db / seed_preset_articles 原本是
    模块级副作用（import server 就建库），测试想隔离数据库只能改 env 再重新 import；
    收进工厂后，调用方可以自己决定何时建库、往哪挂路由。

    装配顺序不是随意的：
    - 两个中间件按"先注册在内层"挂，与搬迁前完全一致（wb CORS 在外层，可短路预检）；
    - register_routes 必须早于静态挂载 —— catch-all 的 "/" 会吃掉其后所有路径。
    """
    app = FastAPI(title="DeLector")
    app.middleware("http")(add_frontend_no_cache_headers)
    app.middleware("http")(_wb_sync_cors)
    register_routes(app)
    init_db()
    seed_preset_articles()
    if STATIC_DIR and os.path.exists(STATIC_DIR):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


# 模块级单例：uvicorn 与 `from delector.server import app` 的既有入口保持不变
# （start.py、全部 TestClient 夹具都依赖它）；工厂只是把装配过程显式化、可重放。
app = create_app()
