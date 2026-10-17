import asyncio
from typing import Any, Dict

import pytest

from delector import server

# ── TTS 并发闸（k=4，把无界排队变成有界 429）───────────────────────────────
#
# 背景：generate_edge_tts_audio 内部走 asyncio.to_thread（默认池
# min(32, cpu+4)），池满后 asyncio **无界排队**而非拒绝；叠加 edge_tts 无显式
# 超时 + services/tts.py 对任意异常重试一次 + main.py 降级 3 个 HTTP provider
# 各 6s ⇒ 单请求最坏约 76s。docker-compose 把 0.0.0.0:8000 全网暴露，局域网
# 多设备（或同一设备多个 <audio> 同时起播）足以把线程池打满、请求无界堆积。
#
# 契约：MUST 把无界排队变成**有界拒绝**（429），MUST NOT 只是加延时；
# Semaphore MUST 是模块级（每请求新建 ⇒ 限流形同虚设）；GET 与 POST 两个入口
# 都要加（<audio src> 走 GET，最容易漏）。MUST NOT 让正常单用户请求开始失败，
# 故生产取值 k=4（局域网默认 1~2 台设备够用）。


@pytest.fixture
def tts_gate(monkeypatch, tmp_path):
    """把 TTS 并发闸压到 k=1，并把音频生成卡成阻塞桩，返回一个跑「并发两请求」的函数。

    压到 1 只是为了**测试不必并发 4 个真实 TTS**（那会真打 edge_tts 网络）；
    生产常量仍是 4，并另有一条上界断言钉住「k 必须有界」——
    有人把 k 调成 1_000_000（闸形同虚设）时，是那条断言先红。

    返回的 scenario(method, second_override=None) ⇒ (第一个请求的响应, 第二个请求的响应)：
    第一个请求在桩里 await 到测试放行为止，故第二个请求抵达时闸必然已被占住。

    second_override 用于把**第二个**请求的入参改坏（``{"voice": ...}`` / ``{"rate": ...}``），
    用来验证「闸满不会压掉入参校验的 400 语义」——这条收益 MUST 有测试钉住，
    否则把闸挪回路由入口（校验之前）就没人拦了。
    """
    from delector.routes import main as routes_main

    assert 1 <= routes_main._TTS_CONCURRENCY_LIMIT <= 8, (
        f"TTS 并发上限必须是有界的（当前 {routes_main._TTS_CONCURRENCY_LIMIT}）："
        "无界 ⇒ 线程池打满后请求无界堆积，等于根本没设闸"
    )

    fake_mp3 = tmp_path / "gate.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00gate_audio")

    # 换掉模块级那把闸（monkeypatch 负责还原，避免污染其它用例）
    monkeypatch.setattr(routes_main, "_TTS_SEMAPHORE", asyncio.Semaphore(1))

    async def scenario(method: str, second_override: Any = None) -> Any:
        import httpx

        entered = asyncio.Event()
        release = asyncio.Event()

        async def _blocking_tts(*_args: Any, **_kwargs: Any) -> str:
            entered.set()
            await release.wait()
            return str(fake_mp3)

        monkeypatch.setattr(routes_main, "generate_edge_tts_audio", _blocking_tts)

        async def one(client: Any, override: Any = None) -> Any:
            if method == "get":
                params: Dict[str, Any] = {"text": "hallo"}
                params.update(override or {})
                return await client.get("/api/audio/tts", params=params)
            body: Dict[str, Any] = {"text": "hallo"}
            body.update(override or {})
            return await client.post("/api/audio/tts", json=body)

        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = asyncio.create_task(one(ac))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
            except asyncio.TimeoutError:
                release.set()
                pytest.fail("第一个 TTS 请求没进到音频生成桩：并发用例的前置条件不成立")
            try:
                second = await asyncio.wait_for(one(ac, second_override), timeout=5)
            except asyncio.TimeoutError:
                release.set()
                await first
                pytest.fail(
                    "第二个 TTS 请求既没被拒（429）也没返回：闸退化成了无界排队，"
                    "只该拒绝不该让它等"
                )
            release.set()
            return await first, second

    return scenario


def test_tts_concurrency_gate_rejects_overflow_on_post(tts_gate):
    """POST /api/audio/tts：第一个请求占住闸 ⇒ 第二个 MUST 拿 429（有界拒绝）。"""
    first, second = asyncio.run(tts_gate("post"))

    assert first.status_code == 200, f"第一个请求应正常出声，实际 {first.status_code}"
    assert second.status_code == 429, (
        f"并发已满时第二个 POST 必须被拒（429），实际 {second.status_code}："
        "无界排队会让最坏 76s 的合成请求堆死线程池"
    )


def test_tts_concurrency_gate_rejects_overflow_on_get(tts_gate):
    """GET /api/audio/tts 同样 MUST 有闸——``<audio src>`` 走的就是这个入口，最容易漏。"""
    first, second = asyncio.run(tts_gate("get"))

    assert first.status_code == 200, f"第一个请求应正常出声，实际 {first.status_code}"
    assert second.status_code == 429, (
        f"并发已满时第二个 GET 必须被拒（429），实际 {second.status_code}："
        "<audio src> 直连 GET，漏了它就等于给绕过闸开了一条路"
    )


def test_tts_concurrency_gate_429_detail_is_human_readable(tts_gate):
    """429 的 detail MUST 是人话：非空，且不含 traceback / 内部路径等内部信息。"""
    _first, second = asyncio.run(tts_gate("post"))

    assert second.status_code == 429
    detail = second.json()["detail"]
    assert isinstance(detail, str) and detail.strip(), f"429 detail 不该为空：{detail!r}"

    leaked = ["Traceback", 'File "', "delector\\", "delector/", "/api/", "_TTS_SEMAPHORE", "semaphore"]
    for marker in leaked:
        assert marker not in detail, f"429 detail 泄露了内部信息 {marker!r}：{detail!r}"


def test_tts_gate_does_not_hide_validation_errors(tts_gate):
    """闸满 + 入参非法 ⇒ MUST 仍是 400，MUST NOT 变成 429「并发已满，请稍后重试」。

    闸在**入参校验之后**：用户填错 voice/rate 是他自己的错，跟并发无关。把它报成
    429 会让人以为「系统忙，等会儿就好」，于是反复重试一个注定 400 的请求——
    而重试又会把本就不够的名额继续占着，自我加剧。

    闸挪回路由入口（= 校验之前）⇒ 本用例必红：拿到的是 429。
    """
    for bad in ({"voice": "not-a-real-voice"}, {"rate": "not-a-rate"}):
        _first, second = asyncio.run(tts_gate("post", bad))

        assert second.status_code == 400, (
            f"闸满时非法入参 {bad} 仍应报 400（用户自己的错），"
            f"实际 {second.status_code}（{second.text[:200]}）："
            f"把入参错误报成 429 会误导成「稍后重试」，"
            f"并且让注定失败的请求继续吃名额"
        )


def test_tts_single_request_not_blocked_by_gate(client, monkeypatch, tmp_path):
    """不回归：单请求（非并发）MUST 200——闸拦的是超载，不是正常单用户朗读。"""
    from unittest.mock import AsyncMock

    fake_mp3 = tmp_path / "single.mp3"
    fake_mp3.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00single_audio")
    monkeypatch.setattr("delector.routes.main.generate_edge_tts_audio", AsyncMock(return_value=str(fake_mp3)))

    res = client.post("/api/audio/tts", json={"text": "Guten Tag", "voice": "de-DE-KatjaNeural"})
    assert res.status_code == 200, f"单请求不该被并发闸误伤，实际 {res.status_code}：{res.text[:200]}"

    res_get = client.get("/api/audio/tts", params={"text": "Guten Tag"})
    assert res_get.status_code == 200, f"单请求 GET 也不该被误伤，实际 {res_get.status_code}"


# ── GET /api/health（子计划4 Task 4：真健康端点）──────────────────────────────
# 背景：Go agent 此前拿 `GET /api/tools/` 当健康探针，而它**只枚举工具、完全不碰
# 数据库** ⇒ 库损坏/磁盘掉线时它照样回 200，agent 认为"服务健康"继续把调用打过来。
# 本组用例钉住：健康端点 MUST 真查库；库不可用时 MUST 非 200，且失败响应 MUST NOT
# 泄露路径/异常栈/异常类名（探针响应会经日志与监控外流）。
#
# 惯例（非本组用例的断言对象，但记在这里免得被"顺手加个本机闸"改掉）：
# 只读 GET 一律不挂 `_require_localhost` —— 全仓 16 处该闸全在写/密钥/备份类端点上。


def test_health_endpoint_ok_when_db_usable(client):
    """库可用 ⇒ 200，且明确报出"库这一层是通的"（探针要能区分"进程活着"与"库活着"）。"""
    res = client.get("/api/health")

    assert res.status_code == 200, f"库可用时健康端点应为 200，实际 {res.status_code}：{res.text[:200]}"
    body = res.json()
    assert body["status"] == "ok", f"200 响应应带 status=ok，实际 {body}"
    assert body["database"] == "ok", f"200 响应应带 database=ok（证明真查了库），实际 {body}"
    # 身份字段（ADR-0020 §4 前置①）：桌面壳启动期必须能凭 /api/health 分辨「这是不是
    # DeLector」，以消除「复用别人的端口 / 跑旧进程」两类静默失败。故版本与标识都要在。
    from delector.core.version import APP_VERSION

    assert body["app"] == "delector", f"200 响应应带 DeLector 身份 app=delector（供启动期身份探针），实际 {body}"
    assert body["version"] == APP_VERSION, (
        f"200 响应应带 version 且与 version.py 单一真相源一致，实际 {body} vs {APP_VERSION!r}"
    )


def test_health_endpoint_fails_when_db_connection_raises(client, monkeypatch, tmp_path):
    """**核心**：DB 连接抛错 ⇒ MUST 非 200，且响应体 MUST NOT 泄露路径/栈/异常类名。

    把库路径塞进异常消息里（`unable to open database file: <path>` 是 sqlite3 的
    真实措辞），再用该路径字符串做否定断言 —— 只断言"不含 Traceback"是不够的：
    一条裸路径泄露的杀伤力与栈同级。
    """
    import sqlite3

    from delector.routes import main as routes_main

    secret_path = str(tmp_path / "gone" / "delector.db")

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError(f"unable to open database file: {secret_path}")

    monkeypatch.setattr(routes_main, "db_conn", _boom)

    res = client.get("/api/health")

    assert res.status_code != 200, (
        f"库连不上却回 200，等于把本 Task 要修的病根又装回去：{res.status_code} {res.text[:200]}"
    )
    assert res.status_code == 503, f"库不可用应是 503（Service Unavailable），实际 {res.status_code}"

    body = res.json()
    assert body["status"] == "unhealthy", f"失败响应应带 status=unhealthy，实际 {body}"
    # 身份契约必须钉在**真实 503 路由**上：库坏时也要带 app=delector。`probe_identity` 的
    # 契约是「接受 503、只看身份」—— 缺了它，第二次启动会把「自己的降级实例」误报成
    # 「端口被其他程序占用」。只测手搓的假 503 形状给的是假安心，唯有这条路由级断言作数。
    assert body.get("app") == "delector", (
        f"503 必须带 DeLector 身份字段（供 probe_identity 分辨「自己的降级实例」与「别人的端口」），实际 {body}"
    )
    detail = body["detail"]
    assert isinstance(detail, str) and detail.strip(), f"失败原因不该为空：{body}"

    for marker in ("Traceback", 'File "', "sqlite3", "OperationalError", secret_path, "delector\\", "delector/"):
        assert marker not in res.text, f"健康端点失败响应泄露了内部信息 {marker!r}：{res.text[:300]}"


def test_health_endpoint_fails_when_db_query_raises(client, monkeypatch):
    """DB 连得上但**查询**抛错（库文件损坏）⇒ 同样 MUST 非 200。

    上一条只覆盖"连不上"；这一条覆盖"连上了但读不动"。少了它，把探测换成
    "只开连接不查询"（或只查一个 sqlite 不读页的元数据）也能骗过上一条用例。
    """
    import contextlib
    import sqlite3

    class _CorruptedConn:
        def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise sqlite3.DatabaseError("database disk image is malformed")

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    @contextlib.contextmanager
    def _broken_db_conn(*_args: Any, **_kwargs: Any) -> Any:
        yield _CorruptedConn()

    monkeypatch.setattr("delector.routes.main.db_conn", _broken_db_conn)

    res = client.get("/api/health")

    assert res.status_code == 503, (
        f"库文件损坏（连得上但查询炸）仍应报 503，实际 {res.status_code}：{res.text[:200]}"
    )
    assert res.json().get("app") == "delector", (
        "查询抛错的 503 同样必须带身份（probe_identity 接受任意 503、只看身份），"
        f"否则会把自己的降级实例误判为陌生端口。实际 {res.json()}"
    )
    assert "database disk image is malformed" not in res.text, f"原始异常消息泄露到了响应体：{res.text[:300]}"
