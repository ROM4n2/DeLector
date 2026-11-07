#!/usr/bin/env python3
"""真实请求验证设置页四档思考强度在上游是否产生可区分响应。

用法（仓库根目录）：
    python tools/probe_reasoning_effort.py

读取当前设置里的 key / base_url / model（与 App 同源），依次发送四档请求，打印：
    - 实际发出的 reasoning_effort（经过与生产一致的映射）
    - HTTP 状态与耗时
    - reasoning_content 字符数
    - usage 里的 prompt/completion tokens

只用标准库 + httpx（项目已有依赖）。不会把 key 打印出来。
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    """读取仓库根的 .env 补进 os.environ（已存在的同名变量不覆盖，方便临时换 key）。"""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip("'").strip('"')


_load_env()

import httpx  # noqa: E402

from delector.core.db.settings import (  # noqa: E402
    get_effective_api_base_url,
    get_effective_api_key,
    get_effective_api_model,
    get_effective_reasoning_effort,
)
from delector.services.llm_client import map_reasoning_effort  # noqa: E402

TIERS = ["none", "low", "medium", "high"]
PROMPT = "Erkläre in zwei Sätzen, warum der Himmel blau ist."


async def probe(tier: str, key: str, base_url: str, model: str, max_tokens: int) -> None:
    upstream = map_reasoning_effort(tier)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": max_tokens,
        "reasoning_effort": upstream,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=payload)
    except Exception as exc:  # noqa: BLE001 - 探针需要把所有失败都打印出来
        print(f"{tier:6} -> {upstream:4} | EXC {exc!r} | {time.monotonic() - started:.2f}s")
        return
    elapsed = time.monotonic() - started
    if resp.status_code != 200:
        print(f"{tier:6} -> {upstream:4} | HTTP {resp.status_code} | {elapsed:.2f}s | {resp.text[:200]}")
        return

    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    reasoning = message.get("reasoning_content") or ""
    usage = data.get("usage") or {}
    print(
        f"{tier:6} -> {upstream:4} | HTTP 200 | {elapsed:6.2f}s "
        f"| reasoning_chars={len(reasoning):5d} "
        f"| prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} "
        f"| finish={choice.get('finish_reason')}"
    )


async def main() -> int:
    key = get_effective_api_key()
    base_url = get_effective_api_base_url()
    model = get_effective_api_model()
    current = get_effective_reasoning_effort()
    if not key:
        print("缺少 API key：请在设置页填写，或配置 DEEPSEEK_API_KEY 环境变量。")
        return 2
    print(f"base_url={base_url} model={model} 当前档位={current}（本探针会依次覆盖四档）")
    print(f"key_len={len(key)}\n")
    for tier in TIERS:
        await probe(tier, key, base_url, model, max_tokens=4096)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
