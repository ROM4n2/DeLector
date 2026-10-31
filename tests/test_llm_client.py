# -*- coding: utf-8 -*-
"""delector.services.llm_client 的契约测试（**全 stub，绝不发真请求**）。

背景（Task 3 · LLM client 收口）：`delector/routes/main.py` 曾有 5 处重复的
`httpx.AsyncClient + /chat/completions + Authorization + json.loads`，且**生成路径
零 max_tokens**（输出上界不可控，是 Task 4 循环预算的前置欠账）。收口后本文件钉住：

1. payload **MUST** 含 `max_tokens`（调用方传值或落到有界默认值）；
2. `timeout` 由调用方透传（保留各处现值 30/15/20/10/30 的语义空间）；
3. HTTP 非 200 ⇒ `LLMError`（调用方据此映射成现状的 502）；
4. 非 JSON 响应 / 非 JSON 内容 / 畸形信封各有明确失败语义。

隔离纪律：用 httpx 官方 `MockTransport`（进程内 transport，请求根本不出网卡），
因此**不需要、也绝不允许**依赖真实 `DEEPSEEK_API_KEY` —— 本仓 ADR 明令：依赖真 key
的测试在门禁上恒 skip，等于没有测试。
"""

import asyncio
import io
import json
import os
import tokenize
from typing import Any, Callable, Dict, List

import httpx
import pytest

from delector.services import llm_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 桩 base_url：`.invalid` 是 RFC 2606 保留域，即便桩失效也注定连不通 —— 兜底证明不出网。
_STUB_BASE_URL = "http://llm-stub.invalid/v1"
_MSGS: List[Dict[str, str]] = [{"role": "user", "content": "Sag 'OK'."}]

Handler = Callable[[httpx.Request], httpx.Response]

# ── 收口守卫的白名单（见 `test_main_routes_converged_on_single_client`） ──────────
# main.py 里唯一允许保留的裸 httpx 出口：TTS 兜底（多供应商纯 Python 回退：
# dict.youdao / fanyi.baidu / translate.google 三家公开 TTS 的 GET）。
# 为什么它可以留：它打的不是 LLM，不带 Authorization / response_format / json.loads
# 那套 LLM 契约，也不碰 /chat/completions ⇒ 不在本次 LLM 收口范围。
# 行号只作定位提示：无关编辑会让行号漂移，硬判行号 ⇒ 守卫假红 ⇒ 最终被人删掉；
# 真正的判据是**行内容**（marker），行号仅用于报错时告诉你去哪看。
_TTS_FALLBACK_HTTPX_LINE = 1233
_TTS_FALLBACK_HTTPX_MARKER = "async with httpx.AsyncClient(timeout=6.0) as client:"
# 收口前 main.py 的 5 处裸 LLM 出网（413 / 516 / 1449 / 1544 / 2374）⇒ 收口后必须恰好 5 处。
_EXPECTED_CONVERGED_CALLS = 5


def _ok(content: str) -> httpx.Response:
    """标准 OpenAI 形状的响应信封（`choices[0].message.content = content`）。"""
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler: Handler) -> List[Dict[str, Any]]:
    """把 `llm_client` 用的 `httpx.AsyncClient` 换成「记录构造参数 + MockTransport」的桩。

    返回每次构造的 kwargs 列表（用于断言 `timeout` 透传）。真身 `AsyncClient` 仍被使用，
    只是 transport 指向进程内桩 —— 请求不出网卡，也不需要任何真实凭据。
    """
    real_cls = httpx.AsyncClient
    recorded: List[Dict[str, Any]] = []

    def _factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        recorded.append(kwargs)
        return real_cls(transport=httpx.MockTransport(handler), timeout=kwargs.get("timeout", 5.0))

    monkeypatch.setattr(llm_client.httpx, "AsyncClient", _factory)
    return recorded


def _chat(**kwargs: Any) -> Dict[str, Any]:
    """同步跑一次 chat()：本仓无 pytest-asyncio（见既有测试的 `asyncio.run` 惯例）。"""
    return asyncio.run(llm_client.chat(**kwargs))


def test_chat_payload_must_carry_max_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    """payload MUST 含 `max_tokens` —— 这是收口的核心欠账（生成路径原先零设置）。"""
    seen: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return _ok('{"definition_zh": "挑战"}')

    _install_mock_transport(monkeypatch, handler)

    out = _chat(
        messages=_MSGS,
        model="deepseek-chat",
        max_tokens=1234,
        timeout=7.0,
        api_key="sk-stub",
        base_url=_STUB_BASE_URL,
    )

    assert out == {"definition_zh": "挑战"}
    assert "max_tokens" in seen["payload"], "payload 必须带 max_tokens（输出上界不可控是本次要还的欠账）"
    assert seen["payload"]["max_tokens"] == 1234
    assert seen["payload"]["model"] == "deepseek-chat"
    assert seen["payload"]["messages"] == _MSGS
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-stub"


def test_chat_default_max_tokens_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """调用方不显式给值时也要有上界（Task 4 循环预算的前置）：默认值 MUST 是正数常量。"""
    seen: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return _ok("{}")

    _install_mock_transport(monkeypatch, handler)
    _chat(messages=_MSGS, model="m", timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert llm_client.DEFAULT_MAX_TOKENS > 0
    assert seen["payload"]["max_tokens"] == llm_client.DEFAULT_MAX_TOKENS


def test_timeout_is_passed_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """timeout 由调用方透传（30/15/20/10/30 各处现值不变）⇒ 必须原样喂给 AsyncClient。"""
    recorded = _install_mock_transport(monkeypatch, lambda request: _ok("{}"))

    _chat(messages=_MSGS, model="m", max_tokens=8, timeout=12.5, api_key="k", base_url=_STUB_BASE_URL)

    assert recorded, "chat() 必须真的构造一次 AsyncClient，否则谈不上超时透传"
    assert recorded[0]["timeout"] == 12.5


@pytest.mark.parametrize("status", [401, 402, 429, 500, 503])
def test_http_error_maps_to_llmerror_carrying_502_detail(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """HTTP 非 200 ⇒ LLMError（调用方据此 502）；原始响应正文 MUST 保留以便排障。"""
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(status, text="insufficient balance"))

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    err = excinfo.value
    assert err.status_code == status
    assert "AI 服务异常" in err.detail
    assert str(status) in err.detail
    assert "insufficient balance" in err.raw


def test_non_json_response_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 200 但响应体不是 JSON（网关 HTML 之类）⇒ 明确失败语义，且保留正文。"""
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, text="<html>502 gateway</html>"))

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert excinfo.value.detail == "AI 服务返回非 JSON 响应"
    assert excinfo.value.status_code == 200
    assert "502 gateway" in excinfo.value.raw


def test_non_json_content_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """信封合法但 `content` 不是 JSON ⇒ 另一条明确失败语义（与"响应体非 JSON"区分开）。"""
    _install_mock_transport(monkeypatch, lambda request: _ok("THIS IS NOT JSON"))

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert excinfo.value.detail == "AI 服务返回内容非 JSON"
    assert excinfo.value.raw == "THIS IS NOT JSON"


def test_markdown_code_block_json_content_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型输出用 ```json 包裹时的健壮自愈解析。"""
    wrapped = "```json\n{\"definition_zh\": \"你好\", \"pos\": \"noun\"}\n```"
    _install_mock_transport(monkeypatch, lambda request: _ok(wrapped))

    out = _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)
    assert out["definition_zh"] == "你好"
    assert out["pos"] == "noun"


def test_think_tag_reasoning_is_extracted_and_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek-R1 / Reasoner 带有 <think> 标签时的思考链提取与 JSON 健壮解析。"""
    content = "<think>\n详细分析德语从句五场域拓扑\n</think>\n{\"reply_zh\": \"主从复合句\"}"
    _install_mock_transport(monkeypatch, lambda request: _ok(content))

    out = _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)
    assert out["thought"] == "详细分析德语从句五场域拓扑"
    assert out["reply_zh"] == "主从复合句"


def test_conversational_wrapped_json_content_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """模型在 JSON 外夹带客套前缀/后缀文本时的健壮解析。"""
    content = "分析结果如下：\n{\"word\": \"Buch\", \"gender\": \"n\"}\n祝学习愉快！"
    _install_mock_transport(monkeypatch, lambda request: _ok(content))

    out = _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)
    assert out["word"] == "Buch"
    assert out["gender"] == "n"


def test_malformed_envelope_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """信封缺 `choices[0].message.content` ⇒ 响应格式异常（不能是 KeyError 冒泡）。"""
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"error": {"message": "x"}}))

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert excinfo.value.detail == "AI 服务响应格式异常"


def test_non_object_json_content_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """`content` 是合法 JSON 但不是对象（数组/标量）⇒ 响应格式异常（契约是 dict）。"""
    _install_mock_transport(monkeypatch, lambda request: _ok("[1, 2, 3]"))

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert excinfo.value.detail == "AI 服务响应格式异常"


def test_transport_error_preserves_original_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    """传输层异常（超时/连接失败）⇒ 统一失败语义，但原始错误信息 MUST 留下来排障。"""

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated boom")

    _install_mock_transport(monkeypatch, boom)

    with pytest.raises(llm_client.LLMError) as excinfo:
        _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)

    assert excinfo.value.detail == "AI 服务连接失败"
    assert excinfo.value.status_code is None
    assert "simulated boom" in excinfo.value.raw


def test_optional_fields_absent_until_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """temperature / response_format 不传就不得出现在 payload（保持 5 处现状：连通性自检无 response_format）。"""
    seen: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return _ok("{}")

    _install_mock_transport(monkeypatch, handler)

    _chat(messages=_MSGS, model="m", max_tokens=8, timeout=5.0, api_key="k", base_url=_STUB_BASE_URL)
    assert "temperature" not in seen["payload"]
    assert "response_format" not in seen["payload"]

    _chat(
        messages=_MSGS,
        model="m",
        max_tokens=8,
        timeout=5.0,
        temperature=0.2,
        response_format={"type": "json_object"},
        api_key="k",
        base_url=_STUB_BASE_URL,
    )
    assert seen["payload"]["temperature"] == 0.2
    assert seen["payload"]["response_format"] == {"type": "json_object"}


def test_chat_without_parse_json_returns_raw_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """`parse_json=False`：不解析 `content`（连通性自检路径），成功只看 HTTP 200 + 信封。"""
    _install_mock_transport(monkeypatch, lambda request: _ok("OK"))

    out = _chat(
        messages=_MSGS,
        model="m",
        max_tokens=llm_client.CONNECTIVITY_MAX_TOKENS,
        timeout=10.0,
        parse_json=False,
        api_key="k",
        base_url=_STUB_BASE_URL,
    )

    assert out == {"content": "OK"}, f"parse_json=False 时原样回传 content，不 json.loads：{out}"


def test_connectivity_probe_with_plain_ok_is_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """红卡回归（收口判据被收窄）：连通性自检的探针回 **`OK`（不是 JSON）** MUST 判成功。

    `/api/settings/test-key` 收口前**只认 HTTP 200**（正文根本不解析）⇒ 真实探针回 `OK`
    时判成功。收口后若一律要求 `json.loads(content)`，可用 key 会被报成
    「连接返回错误代码: 200 (OK)」——**错误语义被顺手改坏了**，故这条 MUST 钉住。
    """
    # 先建 TestClient：MockTransport 打桩会顶掉 httpx.AsyncClient，晚建会被桩接走。
    from fastapi.testclient import TestClient

    from delector.server import app

    client = TestClient(app, client=("127.0.0.1", 54321))
    _install_mock_transport(monkeypatch, lambda request: _ok("OK"))

    res = client.post(
        "/api/settings/test-key",
        json={"api_key": "sk-stub", "api_base_url": _STUB_BASE_URL},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True, f"可用的 API Key 被误报成连接失败：{data}"
    assert "latency_ms" in data, f"成功文案与延迟计算没走到：{data}"


def _code_without_comments(src: str) -> str:
    """剥掉注释后的代码文本（判据用代码区，注释里提 `/chat/completions` 不算漏网）。

    用 `tokenize` 定位 COMMENT token 并**原地抹成空格**，而不是重新拼接 token：
    重拼会把 `llm_client.chat(` 拆成 `llm_client` / `.` / `chat` / `(`，计数判据
    当场失真（恒 0 ⇒ 守卫变绿）；正则替换则会误伤字符串里的 `#`。
    """
    lines = [list(line) for line in src.splitlines()]
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        if srow != erow:  # 注释不跨行；真出现了就只抹首行，绝不越行误伤
            ecol = len(lines[srow - 1])
        for col in range(scol, ecol):
            lines[srow - 1][col] = " "
    return "\n".join("".join(line) for line in lines)


def test_main_routes_converged_on_single_client() -> None:
    """收口守卫（**结构判据**，不用字符串匹配）：5 处 LLM 出网 MUST 全走 `llm_client.chat`。

    为什么老判据不行：`'f"{base_url}/chat/completions"' not in src` 只钉住**一种拼接写法**
    —— 换 `base_url + "/chat/completions"` 或先存一个 `url` 变量就绕过去了；再配上
    `count(...) >= 5` 的 `>=`（**新增**一处裸调用时 5 处 llm_client.chat 还在，计数不变）
    ⇒ 老判据对「新增裸出口」永久失明。变异自证实测：新增一处拼接式裸 HTTP 时老判据
    GREEN、本守卫 RED；把已收口调用改回裸 HTTP 时两者都红（那种漏网老判据能抓到）。
    故这里换成三条结构判据。
    """
    # C5 架构解耦：原 main.py 已拆解为 domain routers (audio, articles, writing, settings, main)
    # 扫描这 5 个模块的合并源码，确保 5 处 LLM 调用与 1 处 TTS 兜底结构契约不变
    router_files = ["audio.py", "articles.py", "writing.py", "settings.py", "main.py"]
    merged_src = ""
    for rfname in router_files:
        rpath = os.path.join(ROOT, "delector", "routes", rfname)
        with open(rpath, encoding="utf-8") as fh:
            merged_src += fh.read() + "\n"
    code = _code_without_comments(merged_src)

    # ① 裸 httpx 出口必须恰好 1 处，且必须是白名单里的那一处（audio.py 中的 TTS 兜底）。
    httpx_hits = [(n, ln) for n, ln in enumerate(merged_src.splitlines(), start=1) if "httpx.AsyncClient(" in ln]
    assert len(httpx_hits) == 1, (
        "路由层的裸 httpx.AsyncClient 必须恰好 1 处（TTS 兜底）；"
        f"实际 {len(httpx_hits)} 处，行号 {[n for n, _ in httpx_hits]}"
    )
    line_no, line = httpx_hits[0]
    assert _TTS_FALLBACK_HTTPX_MARKER in line, (
        f"路由层第 {line_no} 行是唯一剩下的裸 httpx 出口，但内容不是白名单里的 TTS 兜底: {line.strip()}"
    )

    # ② 剥注释后的代码区 MUST NOT 出现 /chat/completions（任何拼接写法都算）。
    assert "/chat/completions" not in code, "路由代码区仍有裸写的 /chat/completions 出口（收口未完成）"

    # ③ 5 处调用点 MUST 全在（== 不是 >=：任一处退回裸 HTTP 都要立刻红）。
    assert code.count("llm_client.chat(") == _EXPECTED_CONVERGED_CALLS, (
        f"路由层必须恰好 {_EXPECTED_CONVERGED_CALLS} 处走 llm_client.chat，"
        f"实际 {code.count('llm_client.chat(')} 处"
    )
