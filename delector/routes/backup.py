# -*- coding: utf-8 -*-
"""备份、还原与工作台同步路由模块（Layer 5 运行装配层）。"""

import ipaddress
import json
import socket
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from delector.core.database import (
    _BACKUP_TABLES,
    _PROGRESS_TABLES,
    BACKUP_SETTINGS_IMPORT_WHITELIST,
    BACKUP_TOKEN_TTL_SEC,
    _db_snapshot_guard,
    _issue_pending,
    _pending_backup,
    _pending_wb,
    _replace_tables,
    _require_localhost,
    _take_pending,
    build_backup_payload,
    get_db,
    get_progress_db,
    get_wb_state,
    get_wb_sync_key,
    migrate_a1_records_to_exam_trials,
    regenerate_wb_sync_key,
    save_wb_state,
)
from delector.core.utils import _attachment_headers
from delector.core.wb_auth import require_wb_key
from delector.routes.sync import _SYNC_INSTANCE_ID

router = APIRouter()

_BACKUP_LS_DENYLIST = ("wb.pair.v1",)


@router.get("/api/backup/export")
def export_database_backup(request: Request) -> Any:
    """原始导出端点，保留给脚本/桌面直连使用。

    UI 走 /prepare + /download —— 只有那条路径能带上 localStorage，
    也只有它在 Android WebView 里真的能下载（blob: 到不了 DownloadListener）。
    """
    _require_localhost(request)
    return build_backup_payload()


class PrepareBackupReq(BaseModel):
    local_storage: Dict[str, Any] = {}


@router.post("/api/backup/prepare")
def prepare_backup_download(req: PrepareBackupReq, request: Request) -> Dict[str, Any]:
    """前端提交 localStorage → 后端合成完整备份 → 返回一个 TTL 内有效的下载 token。

    为什么要两步：导航只能是 GET，所以 POST 的响应无法触发浏览器下载；
    而 Android WebView 只在「真 http URL + Content-Disposition」时才走原生下载桥。

    token 不是「一次性」的，而是 TTL 内可重复取：Android 上同一个 URL 会被取
    两次（WebView 嗅探一次、App 侧落盘再取一次），单次有效会让第二次拿到 404
    错误体并把它存成备份。安全性靠 _require_localhost + 128 位随机 token 保证。
    """
    _require_localhost(request)
    payload = build_backup_payload()
    # 凭据键在落盘前被剥掉（权威闸；前端过滤只是纵深第一道，见 _BACKUP_LS_DENYLIST）。
    payload["local_storage"] = {
        k: v for k, v in (req.local_storage or {}).items() if k not in _BACKUP_LS_DENYLIST
    }
    token = _issue_pending(
        _pending_backup,
        payload,
        f"delector_backup_{datetime.now().strftime('%Y-%m-%d')}.json",
    )
    return {"token": token, "filename": _pending_backup["filename"], "expires_in": BACKUP_TOKEN_TTL_SEC}


@router.get("/api/backup/download/{token}")
def download_prepared_backup(token: str, request: Request) -> Any:
    _require_localhost(request)
    payload, filename = _take_pending(_pending_backup, token)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=_attachment_headers(filename),
    )


# ── Workbench backup (同理，Android WebView 对 blob: URL 静默失败) ────────


class WbBackupReq(BaseModel):
    filename: str = "workbench-backup.json"
    payload: Dict[str, Any] = {}


@router.post("/api/wb/backup/prepare")
def wb_prepare_backup(req: WbBackupReq, request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    token = _issue_pending(_pending_wb, req.payload, req.filename)
    return {"token": token, "filename": req.filename, "expires_in": BACKUP_TOKEN_TTL_SEC}


@router.get("/api/wb/backup/download/{token}")
def wb_download_backup(token: str, request: Request) -> Any:
    _require_localhost(request)
    payload, filename = _take_pending(_pending_wb, token)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers=_attachment_headers(filename),
    )


# ── Workbench 进度 server 镜像同步（wb_state）─────────────────────────────
#
# GET /api/wb/state      读镜像。放行局域网：手机/平板拉取不需 key——
#                        「只有能 push 的客户端才需要密钥」是够用的信任模型。
# PUT /api/wb/state      写镜像。须带 X-WB-Key（32 位 hex），否则 403。
# GET /api/wb/state/key  取 key。仅本机 127.0.0.1（_require_localhost）。


class WbStateReq(BaseModel):
    payload: Dict[str, Any] = {}


@router.get("/api/wb/state")
def wb_get_state() -> Any:
    return get_wb_state()


@router.put("/api/wb/state")
def wb_put_state(req: WbStateReq, request: Request) -> Dict[str, Any]:
    require_wb_key(request)
    updated_at = save_wb_state(req.payload or {})
    return {"ok": True, "updated_at": updated_at}


@router.get("/api/wb/state/key")
def wb_get_state_key(request: Request) -> Dict[str, Any]:
    _require_localhost(request)
    return {"key": get_wb_sync_key()}


@router.post("/api/wb/state/key")
def wb_regenerate_state_key(request: Request) -> Dict[str, Any]:
    """重新生成同步密钥（= 撤销配对）：旧 key 立即失效。仅本机可调。"""
    _require_localhost(request)
    return {"key": regenerate_wb_sync_key()}


@router.get("/api/wb/lan-info")
def wb_lan_info() -> Dict[str, Any]:
    """局域网可读主机信息：配对 UI 提示「把 IP 填进手机」用。不含任何机密。

    lan_ip 是尽力而为的探测（本机多网卡时取第一个私有 IPv4），探测不到返回空串，
    UI 应退化为手填地址。instance_id 与 /api/wb/sync/info 同源，用于识别是否同一实例。
    """
    lan_ip = ""
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            try:
                addr = ipaddress.ip_address(ip)
            except ValueError:
                continue
            if addr.is_private and not addr.is_loopback:
                lan_ip = str(ip)
                break
    except Exception:
        lan_ip = ""
    return {
        "hostname": socket.gethostname(),
        "port": 8000,
        "lan_ip": lan_ip,
        "instance_id": _SYNC_INSTANCE_ID,
    }


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
    a1_hoeren_records: List[Dict[str, Any]] = []
    a1_lesen_records: List[Dict[str, Any]] = []
    # v5.2 泛化成绩表；v1/v5.1 备份没有此字段，缺省为空（向后兼容同上）
    exam_trials: List[Dict[str, Any]] = []
    # 遇见区短文表；加入备份/还原（缺省为空以兼容 v1/v5.1/v5.2 旧备份）
    encounter_texts: List[Dict[str, Any]] = []
    # 听力微训 / 长难句精读成绩。这两张表早已在 _BACKUP_TABLES 里，模型却漏了字段：
    # pydantic v2 默认 extra=ignore ⇒ 前端整份 POST 的这两键被静默丢弃，而还原对清单里
    # 每张表无条件 DELETE ⇒ **删光零回灌**、接口仍返回 ok（用户零提示丢训练记录，
    # 2026-10-15 swarm 审计 P0-1）。缺省为空以兼容旧备份（与上面各字段同理）。
    listen_trials: List[Dict[str, Any]] = []
    hard_sentence_trials: List[Dict[str, Any]] = []
    local_storage: Dict[str, Any] = {}


@router.post("/api/backup/restore")
def restore_database_backup(req: RestoreReq, request: Request) -> Dict[str, Any]:
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
                # app_settings 的覆盖**只作用于可导入白名单键**：整表 DELETE 会连带
                # 抹掉 DEEPSEEK_API_KEY（它从不进备份，抹了就再也灌不回来）；
                # API_BASE_URL/API_MODEL 也不导入——恶意备份可把它们指向攻击者服务器，
                # 使下一次 AI 调用把真实 DEEPSEEK_API_KEY 发过去（密钥外泄）。
                conn.executemany(
                    "DELETE FROM app_settings WHERE key = ?",
                    [(k,) for k in BACKUP_SETTINGS_IMPORT_WHITELIST],
                )
                conn.executemany(
                    "INSERT INTO app_settings (key, value) VALUES (?, ?)",
                    [
                        (s["key"], s.get("value"))
                        for s in (payload.get("app_settings") or [])
                        if s.get("key") in BACKUP_SETTINGS_IMPORT_WHITELIST
                    ],
                )
        finally:
            conn.close()

        pconn = get_progress_db()
        try:
            with pconn:
                _replace_tables(pconn, _PROGRESS_TABLES, payload)
        finally:
            pconn.close()

        # v5.1 及更早的备份里 A1 成绩只存在旧表（exam_trials 尚未存在）；
        # 透传读路径已切到泛化表，还原后必须把旧表行迁过来，否则历史"看着
        # 还原成功却读不出来"。迁移按行数对账幂等：v2 备份（两表行数已齐）
        # 到这里就是零写入 no-op。
        migrate_a1_records_to_exam_trials()

        # ADR-0016 Phase 3 / Task 5（restore-then-migrate，Migration-Idempotency §4）：
        # wb_state 镜像**不进备份**（不在 _BACKUP_TABLES），换机还原后 vocab_cards 可能
        # 缺已学词。用当前 wb 快照把可投影词条**只补空 / 幂等**地补回统一池。
        # - 同一 _db_snapshot_guard() 内：投影抛错 ⇒ 与 restore 一起整体回滚（不留半成品）；
        # - 惰性导入/调用（避免顶层拉重依赖）；空 payload ⇒ 无输入，自然 no-op；
        # - MUST NOT 吞异常：project_wb_deck 抛错必须向上冒泡。
        wb_payload = get_wb_state()
        if wb_payload:
            from delector.core.vocab_pool import project_wb_deck

            proj_conn = get_db()
            try:
                with proj_conn:
                    project_wb_deck(proj_conn, wb_payload)
            finally:
                proj_conn.close()

    return {"status": "ok", "message": "全量备份恢复成功"}
