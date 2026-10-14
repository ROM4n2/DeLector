# -*- coding: utf-8 -*-
"""LLM 出网**唯一**收口（Task 3：`main.py` 里 5 处裸 httpx → 单一 client）。

收口前：`delector/routes/main.py` 的 413 / 516 / 1449 / 1544 / 2374 各自写一遍
`httpx.AsyncClient + /chat/completions + Authorization + json.loads`，超时值各写各的
（30 / 15 / 20 / 10 / 30），且**生成路径零 max_tokens** —— 输出上界不可控，是
Task 4 循环预算的前置欠账。

收口后本模块是唯一的出网口。刻意保留的现状（**不许顺手改善**）：

- 超时由调用方传入，各处现值 30/15/20/10/30 原样不动（语义各不相同，收口不改语义）；
- 失败仍是调用方侧的那个 502：本模块只负责把失败封装成 `LLMError`，**文案与现状
  逐字一致**，调用方照旧 `raise HTTPException(502, detail=e.detail)`；
- 判成功的口径照旧是严格 `status_code == 200`（不是 2xx 区间）；
- 连通性自检照旧**不解析正文**（`parse_json=False`）：探针提示词回的是 `OK`，若强制
  `json.loads` 就会把可用 key 报成连接失败 —— 那是错误语义，不是收口该改的东西。

唯一新增的可排障面：`LLMError.raw` 保留原始信息（HTTP 层 = 响应正文，传输层 = 异常
原文），避免收口后"只剩一句中文、原始报错被吞"。
"""

import json
from typing import Any, Dict, List, Optional

import httpx

from delector.core.database import get_effective_api_base_url, get_effective_api_key

# ── 预算常量 ──────────────────────────────────────────────────────────────────
# `max_tokens` 默认值**没有既有来源**：收口前全仓仅一处 max_tokens（连通性自检的 5，
# 见 `main.py` 的 /api/settings/test-key），生成路径一处都没有 ⇒ 无"既有约定上限"可抄。
# 4096 是**保守占位**，不是实测结论：计划 Unknown B 明确「循环真实轮次分布与 token 上界
# 待 Task 4 的 stub 基线给出」。Task 4 定案后改这一个常量即可全链路生效。
DEFAULT_MAX_TOKENS = 4096
# 连通性自检沿用收口前的现值（不是生成路径，别跟着 4096 走）。
CONNECTIVITY_MAX_TOKENS = 5

# 结构化输出开关：4 处生成路径要，连通性自检不要 ⇒ 由调用方决定是否带上。
JSON_OBJECT: Dict[str, str] = {"type": "json_object"}

# 失败文案与收口前逐字一致（调用方直接塞进 HTTPException(502, detail=...)）。
_DETAIL_UPSTREAM = "AI 服务异常"
_DETAIL_RESPONSE_NOT_JSON = "AI 服务返回非 JSON 响应"
_DETAIL_BAD_ENVELOPE = "AI 服务响应格式异常"
_DETAIL_CONTENT_NOT_JSON = "AI 服务返回内容非 JSON"
_DETAIL_CONNECT_FAILED = "AI 服务连接失败"


class LLMError(RuntimeError):
    """`chat()` 的统一失败类型（**不是** HTTPException：HTTP 层语义留给调用方）。

    - `detail`：给终端/前端看的人话，与收口前各处的 detail 逐字一致；
    - `status_code`：HTTP 状态码，传输层失败为 `None`（调用方据此区分"上游回了错"
      与"根本没连上"，如 /api/settings/test-key 的两种文案）；
    - `raw`：排障用原始信息（HTTP 层=响应正文，传输层=异常原文）。
    """

    def __init__(self, detail: str, *, status_code: Optional[int] = None, raw: str = "") -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.raw = raw


def _resp_text(resp: Any) -> str:
    """取响应正文（桩对象可能没有 `.text`，缺失当空串 —— 与收口前的宽容取值一致）。"""
    text = getattr(resp, "text", "")
    return text if isinstance(text, str) else str(text)


def _extract_content(data: Any) -> str:
    """从 OpenAI 形状的信封里取 `choices[0].message.content`（收口前的取值口径）。"""
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:  # KeyError / IndexError / TypeError —— 现状一律归为"格式异常"
        raise LLMError(_DETAIL_BAD_ENVELOPE, raw=str(data)[:500]) from exc
    if not isinstance(content, str):
        raise LLMError(_DETAIL_BAD_ENVELOPE, raw=str(data)[:500])
    return content


async def chat(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    timeout: float,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, str]] = None,
    parse_json: bool = True,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """唯一出网口：发一次 chat/completions，默认返回**解析后的 JSON dict**。

    - `max_tokens` 必进 payload（收口的核心欠账）；不传则落到 `DEFAULT_MAX_TOKENS`；
    - `timeout` 由调用方传入并原样透传给 `httpx.AsyncClient`；
    - 失败一律 `LLMError`，调用方决定 502 / 降级文案 —— 本模块不碰 HTTP 层语义；
    - `parse_json=False`（**仅连通性自检用**）：不解析 `content`，成功只看「HTTP 200 +
      信封合法」，返回 `{"content": <原文>}`。收口前 `/api/settings/test-key` 就是只认
      HTTP 200、正文根本不解析 —— 探针提示词（`Sag 'OK'.`）回的就是 `OK`，不是 JSON；
      若在这里强制 `json.loads`，可用 key 会被报成「连接返回错误代码: 200 (OK)」，
      属于**顺手改坏错误语义**，故这个开关是必须的，不是可选项。
    """
    key = api_key if api_key is not None else get_effective_api_key()
    base = (base_url if base_url is not None else get_effective_api_base_url()).rstrip("/")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
            status = getattr(resp, "status_code", 200)
            if status != 200:
                raise LLMError(f"{_DETAIL_UPSTREAM} ({status})", status_code=status, raw=_resp_text(resp))
            try:
                data = resp.json()
            except Exception as exc:
                raise LLMError(_DETAIL_RESPONSE_NOT_JSON, status_code=status, raw=_resp_text(resp)) from exc
            content = _extract_content(data)
            if not parse_json:
                return {"content": content}
            try:
                parsed = json.loads(content)
            except Exception as exc:
                raise LLMError(_DETAIL_CONTENT_NOT_JSON, status_code=status, raw=content) from exc
            if not isinstance(parsed, dict):
                raise LLMError(_DETAIL_BAD_ENVELOPE, status_code=status, raw=content)
            return parsed
    except LLMError:
        raise
    except Exception as exc:  # 传输层/超时/桩异常 —— 现状统一归为"连接失败"
        raise LLMError(_DETAIL_CONNECT_FAILED, raw=str(exc)) from exc
