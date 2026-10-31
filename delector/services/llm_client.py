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
import re
from typing import Any, Dict, List, Optional

import httpx as httpx

from delector.core.database import get_effective_api_base_url, get_effective_api_key

# ── 预算常量 ──────────────────────────────────────────────────────────────────
# `max_tokens` 默认值**没有既有来源**：收口前全仓仅一处 max_tokens（连通性自检的 5，
# 见 `main.py` 的 /api/settings/test-key），生成路径一处都没有 ⇒ 无"既有约定上限"可抄。
#
# 4096 原是**保守占位**（计划 Unknown B）。Task 4 已用实测把它**定案为保留值**，公式为：
#
#     DEFAULT_MAX_TOKENS  >=  2 × 单轮最坏 completion 需求
#     单轮最坏需求        =  ceil(最坏 completion 字符数 / CHARS_PER_TOKEN_ESTIMATE)
#                        =  ceil(2073 / 3.0) = 691 token        （实测，见下）
#     2 × 691 = 1382      <=  4096                              （余量 2.97× ⇒ 保留）
#
# 实测口径（`delector/services/polish_loop.py` 的"预算实测"段有完整数字表）：
#   - 最坏输入 = 2000 字符（`main.py:2383` 的 `req.text[:2000]`）的真实德语 A1 电子邮件；
#   - 录制桩跑满 3 轮（不出网、不用真 Key）：completion 139 / 139 / **2073** 字符；
#   - **没有真 tokenizer**（本机 `import tiktoken` / `import transformers` 均
#     ModuleNotFoundError）⇒ 走字符折算，`CHARS_PER_TOKEN_ESTIMATE = 3.0` 登记为
#     **UNVERIFIED 假设**（偏保守：德语变音字母常被 BPE 拆多 token ⇒ 高估消耗）。
#     该常量定义在 `polish_loop` 里 —— 本模块**不能反向 import**（`polish_loop` 依赖本模块）。
# 余量 2× 的理由：stub 基线不是真实分布，模型可能回"原文 + 译文 + 逐句讲解"这类明显更长
# 的回复；2× 是给"回复比输入更长"这个已知情形留的，不是随手拍的倍数。
# 这些数字由 `tests/test_ai_polish_loop.py` **现算现比**（不抄过期常量）⇒ 改这一个常量，
# 全链路（per-call 上限 + 循环级总量）与那条闸一起跟着动。
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


def _clean_and_parse_json(content: str) -> Any:
    """健壮解析上游 LLM 返回的 JSON 内容。

    防御真实大模型多见输出形式：
    1. 干净 JSON（快路径，开启 strict=False 允许未转义控制字符如换行/Tab）
    2. 带 <think>...</think> 思考链标签（如 DeepSeek-R1 / Reasoner）
    3. Markdown 代码块包裹：```json ... ``` 或 ``` ... ```
    4. 带有对话前缀/后缀的外围大括号匹配 { ... }
    5. 尾随逗号与格式清洗
    """
    stripped = content.strip()
    if not stripped:
        raise json.JSONDecodeError("Empty content", doc=content, pos=0)

    # 1. 快路径：完全标准的 JSON 文本（允许真实物理换行符）
    try:
        return json.loads(stripped, strict=False)
    except json.JSONDecodeError:  # silent-ok: 阶梯解析候选失败，顺延至下一级 markdown/think 剥离策略
        pass

    # 2. 提取 <think>...</think>（保留思考过程）并剔除
    extracted_think = ""
    think_match = re.search(r"<think>([\s\S]*?)</think>", stripped, flags=re.DOTALL)
    if think_match:
        extracted_think = think_match.group(1).strip()
        stripped = re.sub(r"<think>[\s\S]*?</think>", "", stripped, flags=re.DOTALL).strip()

    # 尝试在剥离 think 标签后直接解析
    if stripped:
        try:
            parsed = json.loads(stripped, strict=False)
            if isinstance(parsed, dict) and extracted_think and not parsed.get("thought"):
                parsed["thought"] = extracted_think
            return parsed
        except json.JSONDecodeError:  # silent-ok: 剥离 think 后的候选解析失败，顺延至代码块提取策略
            pass

    # 3. 剥离 Markdown 代码块 ```json ... ``` 或 ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, flags=re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            parsed = json.loads(candidate, strict=False)
            if isinstance(parsed, dict) and extracted_think and not parsed.get("thought"):
                parsed["thought"] = extracted_think
            return parsed
        except json.JSONDecodeError:  # silent-ok: 代码块候选解析失败，顺延至外围大括号提取策略
            pass

    # 4. 寻找最外层大括号 { ... }
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = stripped[first_brace : last_brace + 1].strip()
        candidate_clean = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            parsed = json.loads(candidate_clean, strict=False)
            if isinstance(parsed, dict) and extracted_think and not parsed.get("thought"):
                parsed["thought"] = extracted_think
            return parsed
        except json.JSONDecodeError:  # silent-ok: 大括号候选解析失败，顺延至数组中括号提取策略
            pass

    # 5. 寻找最外层中括号 [ ... ]（以防上游返回数组）
    first_bracket = stripped.find("[")
    last_bracket = stripped.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        candidate = stripped[first_bracket : last_bracket + 1].strip()
        candidate_clean = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            return json.loads(candidate_clean, strict=False)
        except json.JSONDecodeError:  # silent-ok: 数组候选解析失败，最终回退到原文本由标准解析器响亮抛错
            pass

    # 兜底：由标准 json.loads 抛出原始异常供外层捕获包装
    return json.loads(content, strict=False)


def _extract_content(data: Any) -> str:
    """从 OpenAI 形状的信封里取 `choices[0].message.content`（收口前的取值口径）。"""
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:  # KeyError / IndexError / TypeError —— 现状一律归为"格式异常"
        raise LLMError(_DETAIL_BAD_ENVELOPE, raw=str(data)[:500]) from exc
    if not isinstance(content, str):
        raise LLMError(_DETAIL_BAD_ENVELOPE, raw=str(data)[:500])
    return content


def _extract_usage(data: Any) -> Dict[str, int]:
    """从 OpenAI 形状的信封里取 `usage`（⑦：prompt/completion **分别**归约为非负整数）。

    缺失 / 畸形 ⇒ 两项均 0（不抛）：`usage` 是**附加计量**，它的缺席不构成失败
    （收口前根本没有 usage 面）。归零让「无 usage」与「真 0 token」在记录里同形，
    真值 vs 估算的**对照**由 harness 侧并列呈现（不在本模块做任何"猜"）。
    """
    raw = data.get("usage") if isinstance(data, dict) else None
    out: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
    if isinstance(raw, dict):
        for key in ("prompt_tokens", "completion_tokens"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                continue
            out[key] = int(value)
    return out


async def chat(
    messages: List[Dict[str, Any]],
    *,
    model: str,
    timeout: float,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, str]] = None,
    include_usage: bool = False,
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
    - `include_usage=True`（**新增、opt-in**）：把信封的 `usage`（prompt/completion 分别记）
      合并进返回值（`{"…content 键…", "usage": {...}}`）；默认 False ⇒ 返回形状与收口前逐字
      一致。这是为实验 harness 记录**真 token 消耗**而加的唯一透出面，不改既有任何调用方的语义。
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
            usage = _extract_usage(data)
            if not parse_json:
                result: Dict[str, Any] = {"content": content}
                if include_usage:
                    result["usage"] = usage
                return result
            try:
                parsed = _clean_and_parse_json(content)
            except Exception as exc:
                raise LLMError(_DETAIL_CONTENT_NOT_JSON, status_code=status, raw=content) from exc
            if not isinstance(parsed, dict):
                raise LLMError(_DETAIL_BAD_ENVELOPE, status_code=status, raw=content)
            if include_usage:
                # ⑦ 只**新增** usage 透出（prompt/completion 分别记），**不改既有返回形状**：
                # 默认 `include_usage=False` 时返回逐字仍是解析后的 content 字典，既有调用方零感知
                # （`tests/test_llm_client.py` 的 `out == {"definition_zh": ...}` 因此照旧成立）。
                parsed = {**parsed, "usage": usage}
            return parsed
    except LLMError:
        raise
    except Exception as exc:  # 传输层/超时/桩异常 —— 现状统一归为"连接失败"
        raise LLMError(_DETAIL_CONNECT_FAILED, raw=str(exc)) from exc
