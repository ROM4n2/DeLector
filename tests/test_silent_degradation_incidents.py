# -*- coding: utf-8 -*-
"""Task 8b（无静默降级闸落地）五处「真事故」修复的固件：失败/降级路径 MUST 留痕。

为什么单独一个文件（三选一里的选择与理由）
------------------------------------------
任务书给的落点是「事故的自然测试文件 → 否则 test_check_silent_degradation.py 同域 →
否则独立紧范围文件」。三个后端事故（essays / TTS / parse_rss_feed）的自然归宿都是
`tests/test_server.py` —— 那个文件由并行批次独占（禁止触碰）；而
`tests/test_check_silent_degradation.py` 的明文纪律是「绝不 import delector/**」
（它只按路径加载闸工具本身 + 读 ci.yml）。故取第三项：**独立紧范围文件**，
只钉这一批 5 个事故的「可观测性」契约，不重复 test_server 的端点行为覆盖。

每个用例的形态固定：构造「失败」→ 断言 (a) 原语义不退步（返回值 / 异常形状），
(b) 失败留痕（caplog 里有 delector logger 的 warning）。修复前它们因 (b) 失败（red），
修复后转绿 —— 这正是「失败当前不可见」的机械化证明。

纪律：hermetic（tmp_path / monkeypatch / caplog），不碰仓库数据目录、不发网络请求。
"""

import asyncio
import importlib
import logging
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Literal

import httpx
import pytest
from fastapi import HTTPException

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _delector_warnings(caplog: pytest.LogCaptureFixture) -> List[str]:
    """本批用例的判定口径：delector logger 在 WARNING 及以上的留痕文本。"""
    return [r.getMessage() for r in caplog.records if r.name == "delector" and r.levelno >= logging.WARNING]


# ── 事故 1：connection.py:54 —— 缓存目录创建失败在 import 期完全隐形 ─────────────


def test_audio_cache_dir_failure_is_visible_at_import_time() -> None:
    """import 期 makedirs 失败 ⇒ MUST 有一条 warning；静默时本用例红（这就是事故）。

    实现走**子进程**（干净解释器）：在 import 前把 os.makedirs 换掉，再 import
    delector.core.db.connection —— 复刻的正是真实事故形态（import 期调用失败）。
    不选 importlib.reload 在本进程里复刻：reload 会把 connection 的模块级可变对象
    （`_INITIALIZED_PROGRESS_DBS` 等）换成新对象，而 schema 等模块仍按旧对象判定 ⇒
    集合身份分裂会让后续用例（如 test_import_root_modules 的 server import）递归爆栈。
    """
    script = (
        "import os\n"
        "def _boom(*args, **kwargs):\n"
        "    raise OSError('simulated: cache dir not writable')\n"
        "os.makedirs = _boom\n"
        "import delector.core.db.connection\n"
        "print('IMPORT_OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        # 双端显式钉 UTF-8，不依赖 runner locale：CI 的 Windows runner locale 是 cp1252，
        # 子进程 stderr 里的中文按 locale 严格解码 ⇒ 读取线程 UnicodeDecodeError、
        # proc.stderr 变 None（CI 红在 :74 的 TypeError）。子进程侧同样钉
        # PYTHONIOENCODING：写什么编码就按什么编码读，任何 locale 下都可复现。
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO_ROOT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=120,
    )
    assert proc.returncode == 0 and "IMPORT_OK" in proc.stdout, (
        f"import 必须照常完成（失败是降级不是崩溃）：rc={proc.returncode}\n{proc.stderr}"
    )
    assert "缓存目录创建失败" in proc.stderr, (
        "import 期音频缓存目录创建失败必须留 warning；静默 ⇒ 之后朗读无法落缓存时没有任何现场"
    )


# ── 事故 2：connection.py:171 —— SQLite PRAGMA 静默未生效 ───────────────────────


class _PragmaFailingConnection:
    """替身：row_factory 可赋值，execute 一律抛 OperationalError（模拟 PRAGMA 被拒）。"""

    def __init__(self) -> None:
        self.row_factory: Any = None

    def execute(self, sql: str, *args: Any) -> Any:
        raise sqlite3.OperationalError(f"simulated: cannot set {sql}")


def test_sqlite_pragma_failure_is_visible(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """PRAGMA 未生效 ⇒ MUST 有一条 warning；静默时本用例红（WAL 假设失效却无人知）。"""
    connection_mod = importlib.import_module("delector.core.db.connection")
    with caplog.at_level(logging.WARNING, logger="delector"):
        conn = connection_mod._configure_sqlite_conn(_PragmaFailingConnection())

    assert conn is not None  # 降级语义保留：连接照常返回（不因 PRAGMA 失败拒连）
    assert any("PRAGMA" in msg for msg in _delector_warnings(caplog)), (
        "SQLite PRAGMA 未生效必须留 warning；静默 ⇒ journal_mode/busy_timeout 静悄悄退回默认值"
    )


# ── 事故 3：security.py:366 —— 一条坏 feed 条目静默中止其余解析 ──────────────────


def _rss_item_xml(title: str, link: str) -> str:
    return f"<item><title>{title}</title><link>{link}</link></item>"


def test_rss_bad_entry_does_not_swallow_remaining_entries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """坏条目 ⇒ 跳过该条 + warning，**其余条目继续解析**；修复前整段静默中止（部分=空）。"""
    security = importlib.import_module("delector.core.security")
    real_unescape = security.html.unescape

    def _boom_on_bad_title(text: str) -> str:
        if text == "BAD ENTRY":
            raise ValueError("simulated: one malformed entry")
        return real_unescape(text)

    monkeypatch.setattr(security.html, "unescape", _boom_on_bad_title)
    xml_text = (
        "<rss><channel>"
        + _rss_item_xml("BAD ENTRY", "https://example.invalid/bad")
        + _rss_item_xml("GOOD II", "https://example.invalid/good")
        + "</channel></rss>"
    )
    with caplog.at_level(logging.WARNING, logger="delector"):
        items = security.parse_rss_feed(xml_text)

    assert [item["title"] for item in items] == ["GOOD II"], (
        "一条坏条目不得静默中止其余条目解析（修复前 items==[]：部分结果看起来像完整结果）"
    )
    assert any("跳过" in msg for msg in _delector_warnings(caplog)), (
        "坏条目被跳过必须留 warning（修复前：整段 except 静默吞掉，零痕迹）"
    )


# ── 事故 4：routes/main.py:2830 —— analysis_json 静默保持原始字符串 ──────────────


class _FakeCursor:
    def __init__(self, row: Dict[str, Any]) -> None:
        self._row = row

    def fetchone(self) -> Dict[str, Any]:
        return self._row


class _FakeDbConn:
    """db_conn() 的替身：只实现 get_essay 用到的 execute().fetchone()。"""

    def __init__(self, row: Dict[str, Any]) -> None:
        self._row = row

    def __enter__(self) -> "_FakeDbConn":
        return self

    def __exit__(self, *exc_info: Any) -> Literal[False]:
        return False

    def execute(self, sql: str, params: Any = ()) -> _FakeCursor:
        return _FakeCursor(self._row)


def test_get_essay_corrupt_analysis_json_leaves_trace(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """损坏的 analysis_json ⇒ 形状契约不回归（仍返原始串）+ MUST 留 warning。"""
    routes_main = importlib.import_module("delector.routes.main")
    row = {"id": 7, "analysis_json": "{not-json", "title": "t", "content": "c"}
    monkeypatch.setattr(routes_main, "db_conn", lambda *a, **kw: _FakeDbConn(row))

    with caplog.at_level(logging.WARNING, logger="delector"):
        data = routes_main.get_essay(7)

    assert data["analysis_json"] == "{not-json", "损坏的 analysis_json 仍按原始字符串返回（响应形状契约不回归）"
    assert any("analysis_json" in msg for msg in _delector_warnings(caplog)), (
        "analysis_json 解析失败（响应形状与正常路径不同）必须留 warning；静默 ⇒ 前端拿到两种形状无人知"
    )


# ── 事故 5：routes/main.py:1250 —— 兜底 provider 失败零痕迹 ─────────────────────


class _AllProvidersDownClient:
    """httpx.AsyncClient 替身：任何 GET 都抛 ConnectError（模拟三个兜底 provider 全挂）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_AllProvidersDownClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> Literal[False]:
        return False

    async def get(self, url: str, **kwargs: Any) -> Any:
        raise httpx.ConnectError(f"simulated: provider unreachable: {url}")


def test_tts_fallback_provider_failures_name_the_provider(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """三个兜底 provider 全失败 ⇒ 每条失败 MUST 点名具体 provider；修复前循环内零痕迹。"""
    routes_audio = importlib.import_module("delector.routes.audio")

    # 1) 主路径全堵死：edge_tts 缺席（sys.modules[name]=None ⇒ import 抛 ImportError），
    #    edge_tts_mini 客户端也失败 ⇒ 必然落到三 provider 兜底循环。
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    fake_mini = types.ModuleType("delector.services.tts")

    def _synthesize_boom(text: str, voice: str, rate: str) -> bytes:
        raise RuntimeError("simulated: mini client unreachable")

    fake_mini.synthesize = _synthesize_boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "delector.services.tts", fake_mini)
    import delector.services

    monkeypatch.setattr(delector.services, "tts", fake_mini, raising=False)

    # 2) 三个 HTTP 兜底 provider 全部失败。
    monkeypatch.setattr(routes_audio.httpx, "AsyncClient", _AllProvidersDownClient)
    # 3) 缓存目录指向 tmp：本路径不应落盘，指向 tmp 防任何意外写入。
    cache_dir = tmp_path / "tts_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(routes_audio, "AUDIO_CACHE_DIR", str(cache_dir))

    with caplog.at_level(logging.WARNING, logger="delector"):
        with pytest.raises(HTTPException) as excinfo:
            asyncio.run(routes_audio.generate_edge_tts_audio("Hallo Welt", "de-DE-KatjaNeural", "+0%"))

    assert excinfo.value.status_code == 500, "全失败仍 MUST 上抛 HTTPException(500)（对外文案契约不变）"
    warnings_text = "\n".join(_delector_warnings(caplog))
    for host in ("dict.youdao.com", "fanyi.baidu.com", "translate.google.com"):
        assert host in warnings_text, (
            f"兜底 provider 失败必须能点名具体 provider：{host} 未出现在 warning 里"
            "（修复前：循环内零痕迹，循环后的总警告点不出失败的是哪个）"
        )