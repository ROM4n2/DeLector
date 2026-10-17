# -*- coding: utf-8 -*-
"""备份 / 还原域的端点测试（C6 Task 3 自 `tests/test_server.py` 逐字搬出）。

搬出的三段（搬前 `test_server.py` 行号，实测，含各段头注释）：
  `713`-`1167`  v3.10.0 备份往返回归 + 备份 prepare/download 令牌生命周期 +
          wb.pair 凭据闸 + attachment 头 / 前端导出守卫（同一头段下的备份域簇）。
  `3014`-`3113`  v4.4 Task6 / 6.1 Backup source boundary（prepare/download/restore）。
  `4526`-`4680`  ADR-0016 Phase 3 / Task 5：备份列清单补齐 + 还原后补迁移。

断言与用例名逐字未改；只新增本文件的显式 import。共享夹具（clean_db / client /
lan_client / test_db_path）住在 `tests/server_helpers.py` 与 `tests/conftest.py`，
按名即可见，无需本文件重复定义。
"""

import json
import os
import re
import time

import pytest
from fastapi.testclient import TestClient
from server_helpers import ROOT
from server_helpers import clean_db as clean_db
from server_helpers import lan_client as lan_client
from server_helpers import test_db_path as test_db_path

from delector import server
from delector.core.database import db_conn, db_progress_conn
from delector.server import BACKUP_FORMAT_VERSION, BACKUP_SETTINGS_WHITELIST, app, set_setting

# ── v3.10.0 备份往返修复的回归测试 ────────────────────────────────────────────
# 上面那个 roundtrip 测试只断言了文章标题，正是它让「还原丢掉 SRS 状态」
# 这个数据丢失缺陷一路绿灯。下面把每一处都钉死。


def _vocab_card_with_srs(card_id=501):
    return {
        "id": card_id,
        "article_id": None,
        "word": "warten",
        "lemma": "warten",
        "pos": "VERB",
        "gender": "None",
        "plural": "",
        "cefr_level": "A2",
        "definition_zh": "等待",
        "sentence_context": "Ich warte auf dich.",
        "created_at": "2026-08-01 10:00:00",
        "mastered": 1,
        "mastered_at": "2026-08-15 09:00:00",
        "correct_count": 7,
        "wrong_count": 2,
        "due_date": "2026-12-24",
        "interval_days": 43,
        "ease_factor": 2.87,
        "repetition_count": 5,
    }


def test_restore_preserves_srs_state(client):
    """还原必须带回全部 SM-2/FSRS 字段。

    旧实现的 INSERT 列表不含这 8 列，且用 INSERT OR REPLACE，
    于是导出的 JSON 明明带着复习历史，还原一圈却全部回落到 schema 默认值。
    """
    card = _vocab_card_with_srs()
    res = client.post("/api/backup/restore", json={"version": 2, "vocab_cards": [card]})
    assert res.status_code == 200

    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE id = 501").fetchone())
    for col in (
        "mastered",
        "mastered_at",
        "correct_count",
        "wrong_count",
        "due_date",
        "interval_days",
        "ease_factor",
        "repetition_count",
    ):
        assert row[col] == card[col], f"{col} 未被还原：{row[col]!r} != {card[col]!r}"


def test_export_includes_srs_columns(client):
    """导出侧同样要断言——否则「导出完整」这个前提哪天悄悄坏掉不会有人知道。"""
    client.post("/api/backup/restore", json={"version": 2, "vocab_cards": [_vocab_card_with_srs()]})
    data = client.get("/api/backup/export").json()
    assert data["version"] == BACKUP_FORMAT_VERSION
    exported = next(c for c in data["vocab_cards"] if c["id"] == 501)
    assert exported["ease_factor"] == 2.87
    assert exported["repetition_count"] == 5
    assert exported["due_date"] == "2026-12-24"


def test_progress_db_roundtrips(client):
    """progress.db 三张表进备份——连胜/测验历史/趋势全靠它。"""
    payload = {
        "version": 2,
        "study_log": [
            {"id": 1, "event_type": "add_card", "ref_id": 42, "note": "t", "logged_at": "2026-08-10 08:00:00"}
        ],
        "quiz_log": [
            {
                "id": 1,
                "card_id": 42,
                "card_type": "vocab",
                "mode": "recall",
                "correct": 1,
                "attempted_at": "2026-08-10 08:05:00",
            }
        ],
        "daily_summary": [
            {
                "date": "2026-08-10",
                "cards_added": 3,
                "cards_mastered": 1,
                "articles_read": 2,
                "quiz_sessions": 1,
                "study_minutes": 25,
            }
        ],
    }
    assert client.post("/api/backup/restore", json=payload).status_code == 200

    with db_progress_conn("test_progress.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM study_log").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM quiz_log").fetchone()[0] == 1
        summary = dict(conn.execute("SELECT * FROM daily_summary").fetchone())
    assert summary["study_minutes"] == 25
    assert summary["cards_added"] == 3

    exported = client.get("/api/backup/export").json()
    assert exported["daily_summary"][0]["study_minutes"] == 25
    assert exported["quiz_log"][0]["mode"] == "recall"


def test_export_whitelists_settings_and_never_leaks_api_key(client):
    """备份 JSON 会被分享/上传——API key 绝不能在里面。"""
    set_setting("DEEPSEEK_API_KEY", "sk-should-never-be-exported", db_path="test_delector.db")
    set_setting("TTS_VOICE", "de-DE-ConradNeural", db_path="test_delector.db")

    data = client.get("/api/backup/export").json()
    keys = {s["key"] for s in data["app_settings"]}
    assert "TTS_VOICE" in keys
    assert "DEEPSEEK_API_KEY" not in keys
    assert "DEEPSEEK_API_KEY" not in set(BACKUP_SETTINGS_WHITELIST)
    # 整个序列化结果里都不该出现那个值
    assert "sk-should-never-be-exported" not in json.dumps(data)


def test_restore_does_not_wipe_api_key(client):
    """还原是真覆盖，但覆盖范围必须止于白名单键。

    整表 DELETE app_settings 会连带抹掉 DEEPSEEK_API_KEY——它从不进备份，
    抹了就再也灌不回来，用户得重新配一遍 key。
    """
    set_setting("DEEPSEEK_API_KEY", "sk-must-survive-restore", db_path="test_delector.db")
    set_setting("TTS_VOICE", "de-DE-KatjaNeural", db_path="test_delector.db")

    res = client.post(
        "/api/backup/restore",
        json={
            "version": 2,
            "app_settings": [{"key": "TTS_VOICE", "value": "de-DE-ConradNeural"}],
        },
    )
    assert res.status_code == 200

    with db_conn("test_delector.db") as conn:
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings").fetchall()}
    assert rows["DEEPSEEK_API_KEY"] == "sk-must-survive-restore"
    assert rows["TTS_VOICE"] == "de-DE-ConradNeural"


def test_restore_accepts_v1_backup(client):
    """读 v1 是硬要求：迁移用户手里拿的恰恰是 v3.9.1 导出的 v1 文件。

    v1 没有 app_settings / progress 三表 / local_storage 字段，
    缺列的 SRS 值回落到建表默认值即可，不能因缺字段而拒收。
    """
    v1 = {
        "version": 1,
        "articles": [
            {
                "id": 77,
                "title": "V1 Backup",
                "raw_text": "Alt.",
                "processed_json": "{}",
                "source_url": "",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
        "vocab_cards": [
            {
                "id": 77,
                "article_id": 77,
                "word": "alt",
                "lemma": "alt",
                "pos": "ADJ",
                "gender": "None",
                "plural": "",
                "cefr_level": "A1",
                "definition_zh": "旧的",
                "sentence_context": "Alt.",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    }
    assert client.post("/api/backup/restore", json=v1).status_code == 200

    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE id = 77").fetchone())
    assert row["definition_zh"] == "旧的"
    assert row["ease_factor"] == 2.5  # schema 默认值
    assert row["interval_days"] == 1
    assert row["mastered"] == 0


def test_failed_restore_rolls_back_both_databases():
    """还原中途失败必须整体回滚，不能留下「已清库而备份没灌进去」的状态。

    两个 db 是独立文件、无法共处一个事务：主库先清空并提交，
    progress 库随后失败——若无文件级快照，主库数据已经没了。
    这里用重复的 daily_summary 主键制造 IntegrityError。

    用独立的 client（raise_server_exceptions=False）：默认 TestClient 会把
    服务端异常原样抛给调用方，拿不到 500 响应。
    """
    client = TestClient(app, client=("127.0.0.1", 54321), raise_server_exceptions=False)
    with db_conn("test_delector.db") as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert before > 0, "预置文章应存在，否则这个测试证明不了什么"

    bad = {
        "version": 2,
        "articles": [
            {
                "id": 900,
                "title": "Should Not Survive",
                "raw_text": "x",
                "processed_json": "{}",
                "source_url": "",
                "created_at": None,
            }
        ],
        # 同一个 date 两行 → daily_summary 主键冲突
        "daily_summary": [{"date": "2026-08-11"}, {"date": "2026-08-11"}],
    }
    res = client.post("/api/backup/restore", json=bad)
    assert res.status_code >= 500

    with db_conn("test_delector.db") as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        leaked = conn.execute("SELECT COUNT(*) FROM articles WHERE id = 900").fetchone()[0]
    assert after == before, "主库未被回滚：还原失败却把原有文章清掉了"
    assert leaked == 0, "主库未被回滚：失败的还原却留下了新数据"


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/backup/export"),
        ("post", "/api/backup/prepare"),
        ("get", "/api/backup/download/sometoken"),
        ("post", "/api/backup/restore"),
    ],
)
def test_backup_endpoints_reject_lan_clients(lan_client, method, path):
    """桌面端有意绑 0.0.0.0，所以备份端点必须自己挡住局域网。

    否则同 Wi-Fi 的任何人都能拖走整库（export），
    或者——在还原改成真覆盖之后——用一个 POST 清空别人的数据库。
    """
    res = getattr(lan_client, method)(path, **({"json": {}} if method == "post" else {}))
    assert res.status_code == 403


def test_prepare_and_download_backup_is_reusable_within_ttl(client):
    """Android 导出链路：POST 组装（带 localStorage）→ GET 下载（带 attachment 头）。

    为什么不能沿用 blob:：Android WebView 的 DownloadListener 对 blob: URL
    永不触发，且没有 shouldOverrideUrlLoading 兜底，点击是静默无操作。
    真 http URL + Content-Disposition 是这个 App 里唯一被证明能下载的路径。

    为什么 token 是「TTL 内可重复取」而不是单次有效（v4.7.3 改）：
    Android 上同一个下载 URL 会被取两次 —— WebView 为了嗅探 Content-Disposition
    先发一次 GET，App 侧的落盘逻辑再发第二次。单次有效时第一次就烧掉 token，
    第二次拿到 404，于是把 {"detail": "备份链接已失效"} 当成备份存下来：
    用户手里是一份假备份，全程无报错，比直接失败更难发现。
    """
    # 输入刻意带上 wb.pair.v1（配对凭据：内网 host + 长期 wb_sync_key）——前端收集
    # 侧已过滤它，这里模拟「旧版客户端 / 手改请求把它喂进来」，验证后端权威闸独立成立。
    ls = {
        "delector_voice": "de-DE-ConradNeural",
        "delector_companion_custom_svg": "<svg/>",
        "wb.pair.v1": '{"host": "192.168.1.9:8000", "key": "NOT-A-REAL-KEY-0000"}',
    }
    prep = client.post("/api/backup/prepare", json={"local_storage": ls})
    assert prep.status_code == 200
    token = prep.json()["token"]
    assert token and len(token) >= 20

    res = client.get(f"/api/backup/download/{token}")
    assert res.status_code == 200
    assert "attachment" in res.headers["content-disposition"]
    assert ".json" in res.headers["content-disposition"]
    body = res.json()
    assert body["version"] == BACKUP_FORMAT_VERSION
    # 2026-10-15 swarm 审计 P1-1：原断言 `== ls` 把「local_storage 原样透传」钉成了
    # 契约 —— 恰好把凭据键的透传固化成"正确行为"。改为同时钉住两个方向：
    # ① 含 wb.pair.v1 的输入 ⇒ 落盘体**不含**该键（后端按键名黑名单过滤）；
    # ② 正常偏好键（delector_voice / delector_companion_custom_svg）仍原样带上。
    # 这是**强化**而非放宽：旧断言只证明"带上了什么"，新断言另行证明"不该带的被拦掉"，
    # 同时正常键的逐字往返仍被钉死（覆盖面是旧断言的超集）。
    assert "wb.pair.v1" not in body["local_storage"]
    assert body["local_storage"] == {k: v for k, v in ls.items() if k != "wb.pair.v1"}
    assert "articles" in body and "daily_summary" in body

    # TTL 内第二次必须拿到完全相同的内容 —— 这就是 Android 那条链路的实际形态
    again = client.get(f"/api/backup/download/{token}")
    assert again.status_code == 200
    assert again.text == res.text


def test_prepare_backup_strips_wb_pair_credential_keeps_normal_keys(client):
    """P1-1 契约守卫（后端权威闸）：wb.pair.v1 是**凭据键**，任何情况下不得进备份体。

    链路：wb.pair.v1 = {host, key}，key 即 wb_sync_key（长期、不轮换；database.py 里
    `secrets.token_hex(16)`，只有手动撤销才失效），host 是内网地址。后端 app_settings
    侧早已用 BACKUP_SETTINGS_WHITELIST 把它排除（注释写明「备份 JSON 是用户会分享/
    上传网盘的文件」），但 localStorage 这条侧门会被原样带出 —— cards.js 的
    BACKUP_LS_EXCLUDE 只是纵深第一道（旧版客户端 / 手改请求可绕过）⇒ 权威闸必须在
    后端按键名过滤。

    本用例刻意不经过前端语言（直接构造请求体），与 cards.js 那两个源码守卫各自独立：
    删掉后端 _BACKUP_LS_DENYLIST 过滤 ⇒ 本用例必红；把闸下成"值特征匹配"（如扫 32 位
    hex）⇒ 正常键用例段也会被这条守卫纠住口径（本用例只钉键名语义）。
    """
    credential = '{"host": "192.168.1.9:8000", "key": "NOT-A-REAL-KEY-0000"}'
    ls = {
        "wb.pair.v1": credential,
        "wb.words.v1": '{"a": 1}',  # 正常 wb.* 进度键必须照常带上（闸不得误伤）
        "delector_voice": "de-DE-ConradNeural",
    }
    prep = client.post("/api/backup/prepare", json={"local_storage": ls})
    assert prep.status_code == 200
    res = client.get(f"/api/backup/download/{prep.json()['token']}")
    assert res.status_code == 200
    body = res.json()

    assert "wb.pair.v1" not in body["local_storage"], (
        "凭据键 wb.pair.v1 被原样透传进备份 JSON"
        "（拿到文件即可对 http://<host>:8000 发 PUT /api/wb/state / 投 RTC 信令）"
    )
    assert "NOT-A-REAL-KEY-0000" not in res.text, (
        "凭据**值**出现在下载体的其它角落（过滤必须按整键清理，不许只清 local_storage 的顶层）"
    )
    for k in ("wb.words.v1", "delector_voice"):
        assert body["local_storage"].get(k) == ls[k], f"正常键 {k} 被误伤（黑名单只能拦凭据键）"


def test_download_token_expires_after_ttl(client):
    """TTL 过期后必须拒绝，否则一个 token 就变成永久有效。

    用 410 而不是 404，是为了把它和「token 不对」区分开 —— 两者在用户侧的处置
    不同（前者重导一次就行，后者说明链接被截断了）。
    """
    token = client.post("/api/backup/prepare", json={"local_storage": {}}).json()["token"]
    assert client.get(f"/api/backup/download/{token}").status_code == 200

    server._pending_backup["expires_at"] = time.time() - 1
    assert client.get(f"/api/backup/download/{token}").status_code == 410
    # 过期即清空槽位，重放同一个 token 不该复活
    assert client.get(f"/api/backup/download/{token}").status_code == 404


def test_download_rejects_unknown_token(client):
    client.post("/api/backup/prepare", json={"local_storage": {}})
    assert client.get("/api/backup/download/not-the-right-token").status_code == 404


def test_backup_download_response_forbids_caching(client):
    """no-store 是 TTL 改动的配套要求，不是洁癖。

    同一个下载 URL 会被取两次，中间只要有一次拿到 404 错误体，WebView 的 HTTP
    缓存就可能记住它 —— 第二次连服务端都不问，直接把缓存的错误 JSON 交给落盘
    逻辑存成「备份」。这是唯一能绕过 Android 侧内容自检的路径。
    """
    token = client.post("/api/backup/prepare", json={"local_storage": {}}).json()["token"]
    res = client.get(f"/api/backup/download/{token}")
    assert res.status_code == 200
    assert "no-store" in res.headers["cache-control"]
    assert 'filename="' in res.headers["content-disposition"], "RFC 6266 要求 filename 加引号"

    wb = client.post("/api/wb/backup/prepare", json={"payload": {"a": 1}, "filename": "wb-test.json"}).json()
    res2 = client.get(f"/api/wb/backup/download/{wb['token']}")
    assert res2.status_code == 200
    assert "no-store" in res2.headers["cache-control"]
    assert 'filename="wb-test.json"' in res2.headers["content-disposition"]


def test_attachment_headers_are_only_built_by_the_shared_helper():
    """所有 attachment 响应头必须由 utils._attachment_headers 统一生成。

    Phase 1 Task 1 把 helper 从 server.py 抽到 utils.py（打破 routes_a1 → server
    反依赖）后，本守卫随之迁移到包级扫描：手写一份就漏掉 no-store 或引号——
    前者造出假备份，后者让 Android 的 URLUtil.guessFileName 各版本解析不一致
    （拿到 token 当文件名）。
    """
    pkg = os.path.join(ROOT, "delector")
    # T6 后 helper 本体在 delector/core/utils.py（按文件名匹配，包内不重名）
    utils_path = None
    for _root, _dirs, files in os.walk(pkg):
        if "utils.py" in files:
            utils_path = os.path.join(_root, "utils.py")
            break
    assert utils_path, "delector 包内找不到 utils.py"
    utils_src = open(utils_path, encoding="utf-8").read()
    assert "def _attachment_headers" in utils_src, "utils._attachment_headers 定义缺失"
    offenders = []
    for _root, _dirs, files in os.walk(pkg):
        for name in files:
            if not name.endswith(".py") or name == "utils.py":
                continue
            path = os.path.join(_root, name)
            src = open(path, encoding="utf-8").read()
            if "attachment; filename=" in src:
                offenders.append(name)
    assert not offenders, f"{offenders} 手写了 Content-Disposition，请改用 utils._attachment_headers"
    assert utils_src.count("attachment; filename=") == 1, "utils.py 里出现了多份手写的 Content-Disposition"


def test_frontend_export_does_not_use_blob_download():
    """前端导出必须走 prepare→download，不能退回 Blob + <a download>。

    blob: 方案在桌面浏览器上能用、在 Android 上是静默无操作，
    所以它的回归不会有任何报错——只会让用户以为自己有备份。
    只能在源码层立个哨兵。
    """
    src = open(os.path.join(ROOT, "static", "js", "cards.js"), encoding="utf-8").read()
    start = src.index("export async function downloadBackupJson")
    export_fn = src[start : src.index("export function uploadBackupJson")]
    assert "/api/backup/prepare" in export_fn
    assert "/api/backup/download/" in export_fn
    assert "createObjectURL" not in export_fn, "blob: 下载在 Android 上是静默无操作"
    assert "local_storage" in export_fn, "localStorage 必须一起导出（字号/语音/宠物 SVG 只在那里）"


def test_frontend_backup_export_excludes_wb_pair_credential():
    """P1-1 纵深第一道（导出侧）：cards.js 收集备份键时必须排除 wb.pair.v1。

    wb.pair.v1 = {host, key}，key 即长期 wb_sync_key（不轮换、只有手动撤销才失效）
    ⇒ 它绝不能进「用户会分享/上传网盘」的备份 JSON。

    ⚠️ **静态断言（读源码字符串），只能防文本回归、不能替代真机验收**：本仓无 JS
    测试基建，它只证明"正确的代码形状在源码里存在"。真机行为由后端权威闸的端到端
    用例（test_prepare_backup_strips_wb_pair_credential_keeps_normal_keys）兜底。
    把 BACKUP_LS_EXCLUDE 从收集循环里删掉 / 排除表被改名 ⇒ 本用例必红。
    """
    src = open(os.path.join(ROOT, "static", "js", "cards.js"), encoding="utf-8").read()
    m = re.search(r"const BACKUP_LS_EXCLUDE = new Set\(\[([^\]]*)\]\);", src)
    assert m, "cards.js 必须新增 BACKUP_LS_EXCLUDE 排除表（备份凭据键，纵深第一道）"
    assert '"wb.pair.v1"' in m.group(1), "排除表必须点名 wb.pair.v1（配对凭据：长期 wb_sync_key + 内网 host）"

    start = src.index("function backupLocalStorageKeys")
    collect_fn = src[start : src.index("export ", start)]
    assert "BACKUP_LS_EXCLUDE.has(k)" in collect_fn, (
        "导出侧收集键时未按 BACKUP_LS_EXCLUDE 过滤 ⇒ wb.pair.v1 会被写进备份 JSON"
    )


def test_frontend_backup_restore_excludes_wb_pair_credential():
    """P1-1 纵深第一道（还原侧）：cards.js 写回备份里的 localStorage 时必须排除 wb.pair.v1。

    还原侧原为「备份里有什么就写回什么」⇒ 换机还原 = 把长期凭据迁移到新设备，
    恶意备份还能把它指向他人主机。⚠️ 静态断言局限同导出侧用例（防文本回归，
    不替代真机）。只改导出不改还原 ⇒ 本用例必红。
    """
    src = open(os.path.join(ROOT, "static", "js", "cards.js"), encoding="utf-8").read()
    start = src.index("export function uploadBackupJson")
    restore_fn = src[start : src.index("export ", start + 1)]
    assert "BACKUP_LS_EXCLUDE.has(k)" in restore_fn, (
        "还原侧写回未按 BACKUP_LS_EXCLUDE 过滤 ⇒ 备份里的 wb.pair.v1 会被写回本机"
    )


# --- 6.1 Backup source boundary (prepare/download/restore) ---


def test_backup_prepare_rejects_lan(lan_client):
    """非本机不得 prepare 备份（会带上 localStorage 完整数据库）。"""
    res = lan_client.post("/api/backup/prepare", json={"local_storage": {"delector_font_size": "18"}})
    assert res.status_code == 403


def test_backup_download_rejects_lan_even_with_valid_token(client, lan_client):
    """prepare 产生的 token 也不得被局域网下载。"""
    prep = client.post("/api/backup/prepare", json={"local_storage": {"delector_voice": "x"}})
    assert prep.status_code == 200
    token = prep.json()["token"]
    # lan 尝试用同一 token 下载必须被来源闸挡住，而非 404
    res = lan_client.get(f"/api/backup/download/{token}")
    assert res.status_code == 403
    # 回环仍可正常下载（单次有效）
    ok = client.get(f"/api/backup/download/{token}")
    assert ok.status_code == 200
    assert "attachment" in ok.headers.get("content-disposition", "")


def test_backup_restore_lan_does_not_mutate_db(lan_client, test_db_path):
    """被 403 的还原请求不得改库。"""

    # 先写一条已知文章
    with db_conn(test_db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    payload = {
        "version": 2,
        "articles": [
            {
                "id": 9999,
                "title": "Hacked",
                "raw_text": "x",
                "processed_json": "{}",
                "source_url": "",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
    }
    res = lan_client.post("/api/backup/restore", json=payload)
    assert res.status_code == 403
    with db_conn(test_db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        hacked = conn.execute("SELECT COUNT(*) FROM articles WHERE id=9999").fetchone()[0]
    assert after == before
    assert hacked == 0


def test_backup_restore_failure_keeps_original_db(client, test_db_path):
    """还原失败（DB 约束错误）必须通过文件快照回滚，原始文章保持不变。"""
    from fastapi.testclient import TestClient as TC

    from delector import server

    # 用 raise_server_exceptions=False 才能拿到 500 响应而非抛异常
    fail_client = TC(server.app, client=("127.0.0.1", 54322), raise_server_exceptions=False)
    with db_conn(test_db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        titles_before = {r[0] for r in conn.execute("SELECT title FROM articles").fetchall()}
    # daily_summary 主键重复触发 IntegrityError
    bad = {
        "version": 2,
        "articles": [
            {
                "id": 9100,
                "title": "Should Rollback",
                "raw_text": "x",
                "processed_json": "{}",
                "source_url": "",
                "created_at": "2026-01-01 00:00:00",
            }
        ],
        "daily_summary": [{"date": "2026-08-20"}, {"date": "2026-08-20"}],
    }
    res = fail_client.post("/api/backup/restore", json=bad)
    assert res.status_code >= 500
    with db_conn(test_db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        leaked = conn.execute("SELECT COUNT(*) FROM articles WHERE id=9100").fetchone()[0]
        titles_after = {r[0] for r in conn.execute("SELECT title FROM articles").fetchall()}
    assert after == before, "还原失败未回滚主库"
    assert leaked == 0
    assert titles_before == titles_after


def test_backup_loopback_still_succeeds(client):
    """回环来源的完整备份链路仍可用（prepare→download→restore 往返）。"""
    ls = {"delector_font_size": "20"}
    prep = client.post("/api/backup/prepare", json={"local_storage": ls})
    assert prep.status_code == 200
    token = prep.json()["token"]
    dl = client.get(f"/api/backup/download/{token}")
    assert dl.status_code == 200
    body = dl.json()
    assert body["local_storage"] == ls
    # restore 回环成功
    assert client.post("/api/backup/restore", json={"version": 2, "articles": body["articles"][:1]}).status_code == 200


# ── ADR-0016 Phase 3 / Task 5：备份列清单补齐 + 还原后补迁移 ────────────────────
# 两个缺陷锁在同一块：
# ① _BACKUP_TABLES["vocab_cards"] 漏了 Phase 1 新增语义列 ⇒ 「备份→还原」往返静默丢
#    source / fsrs_*（数据丢失）；
# ② wb_state 镜像不进备份 ⇒ 换机还原后已学词的统一池行回不来
#    （restore-then-migrate，Migration-Idempotency §4）。


def _snapshot_vocab_cards() -> "list[dict]":
    """抽 vocab_cards 全量快照（按 id 排序）供逐字比对。"""
    with db_conn("test_delector.db") as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM vocab_cards ORDER BY id").fetchall()]


def test_backup_restore_preserves_pool_semantic_columns(client):
    """① 往返无损（核心）：source / fsrs_* 必须逐字度过「备份(准备/下载)→还原」往返。

    旧列清单漏了这 4 列，_replace_tables 只写清单内列 ⇒ 还原把 source 静默打回默认
    'user'、fsrs_* 清空。
    """
    with db_conn("test_delector.db") as conn:
        conn.execute(
            "INSERT INTO vocab_cards "
            "(word, lemma, definition_zh, sentence_context, source, fsrs_s, fsrs_d, fsrs_lapses) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("Wanderlust", "wanderlust", "漫游欲", "Ich habe Wanderlust.", "official", 1.5, 7.0, 3),
        )

    # 备份：走 Android 导出链路（POST prepare → GET download）。
    token = client.post("/api/backup/prepare", json={"local_storage": {}}).json()["token"]
    payload = client.get(f"/api/backup/download/{token}").json()
    exported = next(c for c in payload["vocab_cards"] if c["word"] == "Wanderlust")
    assert exported["source"] == "official"
    assert exported["fsrs_s"] == 1.5
    assert exported["fsrs_d"] == 7.0
    assert exported["fsrs_lapses"] == 3

    # 还原同一份 ⇒ 这 4 列逐字保留。
    assert client.post("/api/backup/restore", json=payload).status_code == 200
    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE word = 'Wanderlust'").fetchone())
    assert row["source"] == "official", f"source 往返被丢：{row['source']!r}"
    assert row["fsrs_s"] == 1.5, f"fsrs_s 往返被丢：{row['fsrs_s']!r}"
    assert row["fsrs_d"] == 7.0, f"fsrs_d 往返被丢：{row['fsrs_d']!r}"
    assert row["fsrs_lapses"] == 3, f"fsrs_lapses 往返被丢：{row['fsrs_lapses']!r}"


def test_backup_restore_old_backup_defaults_new_columns(client):
    """② 旧备份向后兼容：不含这 4 键的 v2 payload 不得报错，列落建表默认值。"""
    old = {
        "version": 2,
        "vocab_cards": [
            {
                "id": 71,
                "article_id": None,
                "word": "alt",
                "lemma": "alt",
                "pos": "ADJ",
                "gender": "None",
                "plural": "",
                "cefr_level": "A1",
                "definition_zh": "旧的",
                "sentence_context": "Alt.",
                "created_at": "2026-01-01 00:00:00",
                # 刻意不含 source / fsrs_s / fsrs_d / fsrs_lapses（模拟旧备份）
            }
        ],
    }
    assert client.post("/api/backup/restore", json=old).status_code == 200
    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM vocab_cards WHERE id = 71").fetchone())
    assert row["source"] == "user"
    assert row["fsrs_s"] is None
    assert row["fsrs_d"] is None
    assert row["fsrs_lapses"] == 0


def _wb_learned_word_payload() -> dict:
    """一条「已学词」（card.reps=1 过范围闸）的 wb 快照。"""
    return {
        "words": [{"id": "a1-0001", "hw": "der Abfahrt", "gloss": "出发；发车"}],
        "cards": {"a1-0001": {"s": 3.5, "d": 4.2, "lapses": 1, "reps": 1}},
    }


def test_backup_restore_reprojects_wb_deck(client):
    """③ 还原后补投影（restore-then-migrate）：wb_state 不进备份，但已学词必须补回统一池。

    换机还原只带回 vocab_cards；若某已学词不在备份的 vocab_cards 里（旧导出漏词），
    还原必须从 wb 快照把它幂等补投影回 vocab_cards。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    put = client.put("/api/wb/state", json={"payload": _wb_learned_word_payload()}, headers={"X-WB-Key": key})
    assert put.status_code == 200

    # 构造「缺该词」的备份：vocab_cards 置空。
    backup = client.get("/api/backup/export").json()
    backup["vocab_cards"] = []

    assert client.post("/api/backup/restore", json=backup).status_code == 200
    with db_conn("test_delector.db") as conn:
        row = conn.execute(
            "SELECT fsrs_s, fsrs_d, fsrs_lapses FROM vocab_cards WHERE word = ?",
            ("der Abfahrt",),
        ).fetchone()
    assert row is not None, "还原后应从 wb 快照把已学词补投影回 vocab_cards"
    got = dict(row)
    assert got["fsrs_s"] == 3.5, "补投影应带出卡上的 FSRS-6 参数"
    assert got["fsrs_d"] == 4.2
    assert got["fsrs_lapses"] == 1


def test_backup_restore_reprojection_idempotent(client):
    """④ 投影幂等：连做两次还原 → 该词行不重复、值不变。"""
    key = client.get("/api/wb/state/key").json()["key"]
    put = client.put("/api/wb/state", json={"payload": _wb_learned_word_payload()}, headers={"X-WB-Key": key})
    assert put.status_code == 200

    backup = client.get("/api/backup/export").json()
    backup["vocab_cards"] = []

    assert client.post("/api/backup/restore", json=backup).status_code == 200
    assert client.post("/api/backup/restore", json=backup).status_code == 200
    with db_conn("test_delector.db") as conn:
        rows = conn.execute("SELECT * FROM vocab_cards WHERE word = ?", ("der Abfahrt",)).fetchall()
    assert len(rows) == 1, f"重复还原不得产生重复行，实际 {len(rows)} 行"
    assert dict(rows[0])["fsrs_s"] == 3.5, "重复还原不得改动既有值"


def test_backup_restore_projection_failure_rolls_back(client, monkeypatch):
    """⑤ 失败整体回滚（关键）：投影抛错 ⇒ 还原失败，且库内容与还原前逐字一致。

    投影在 _db_snapshot_guard() 内且不吞异常：一旦抛错两个库都从快照整体写回，
    不留「还原了一半」的状态。
    """
    key = client.get("/api/wb/state/key").json()["key"]
    put = client.put("/api/wb/state", json={"payload": _wb_learned_word_payload()}, headers={"X-WB-Key": key})
    assert put.status_code == 200

    before = _snapshot_vocab_cards()
    assert before, "还原前应有 vocab_cards 内容，否则证明不了回滚"

    def _boom(_conn, _payload):
        raise RuntimeError("projection forced failure")

    # 投影在 restore 函数体内惰性 import ⇒ 运行时取到本桩
    monkeypatch.setattr("delector.core.vocab_pool.project_wb_deck", _boom)

    # raise_server_exceptions=False 才能拿到 500 响应而非让异常从 TestClient 冒出
    fail_client = TestClient(app, client=("127.0.0.1", 54321), raise_server_exceptions=False)
    backup = {"version": 2, "vocab_cards": []}
    res = fail_client.post("/api/backup/restore", json=backup)
    assert res.status_code >= 500, "投影抛错应冒泡成 500，而非被吞掉"

    assert _snapshot_vocab_cards() == before, "还原失败必须整体回滚，vocab_cards 不得残留半成品"
