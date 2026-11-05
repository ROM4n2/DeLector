#!/usr/bin/env python3
"""定点安装 spaCy 德语模型：缓存优先 + **有界**重试 + 失败必响。

为什么不用 `python -m spacy download de_core_news_sm`
----------------------------------------------------
它内部只是 `pip install <GitHub Release 的 wheel URL>`。GitHub 的 release 下载端点
偶发持续数分钟的 504（run 41998234884 attempt 1/2 均死在同一步，原文
`ERROR: HTTP error 504 while getting .../de_core_news_sm-3.8.0-py3-none-any.whl`），
而 pip 自带的重试是**紧密循环**（默认 5 次，数秒内打光），扛不住这种量级的抖动。
本脚本在外层加**有界**重试（默认 3 次，15s / 30s 指数退避），并把成功的 wheel
留在缓存目录供 `actions/cache` 复用 —— 命中缓存时**完全不访问网络**。

失败必须**响亮**
----------------
重试耗尽后打印 `::error::` 并以非零码退出。MUST NOT 用 `continue-on-error` 把它
降级成警告：模型缺失会让冷启动基准的 `nlp_path` 从 `spacy` 掉成 `pure`（被测对象
就变了），也会让一批依赖真实词形的用例静默 skip（比红更坏）。

模型来源
--------
只从 spaCy 官方 GitHub Release 取 wheel（ADR-0027 §8：PyPI 上的 `de-core-news-sm`
是 JetBrains 的 Dependency Confusion 占位 stub，绝不使用）。版本号显式钉死，
与 `.github/workflows/*` 里 `actions/cache` 的 key 必须同步改。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import zipfile
from pathlib import Path

#: 官方 Release 的下载前缀（ADR-0027 §8 唯一允许的来源）。
_RELEASE_BASE = "https://github.com/explosion/spacy-models/releases/download"

#: 与 workflow 缓存 key 同步的默认模型版本（`de_core_news_sm-3.8.0`）。
DEFAULT_MODEL = "de_core_news_sm"
DEFAULT_VERSION = "3.8.0"


def _wheel_url(model: str, version: str) -> str:
    """官方 Release 上该模型 wheel 的 URL。"""
    filename = f"{model}-{version}-py3-none-any.whl"
    return f"{_RELEASE_BASE}/{model}-{version}/{filename}"


def _wheel_path(cache_dir: Path, model: str, version: str) -> Path:
    return cache_dir / f"{model}-{version}-py3-none-any.whl"


def _is_valid_wheel(path: Path) -> bool:
    """本地文件是否是**完整**的 wheel（截断的 zip 会让 pip 装到一半才炸）。"""
    if not path.is_file():
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _run(cmd: list[str]) -> int:
    print(f"[spacy-model] $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd, check=False).returncode


def _download(url: str, dest: Path, attempts: int, backoff_base: float) -> bool:
    """有界下载：最多 `attempts` 次，间隔按指数退避递增；成功即返回 True。"""
    for attempt in range(1, attempts + 1):
        # 上一次的残片会让 pip 直接报 "File ... already exists"，先清掉。
        dest.unlink(missing_ok=True)
        print(f"[spacy-model] attempt {attempt}/{attempts}: {url}", flush=True)
        rc = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--retries",
                "2",
                "--timeout",
                "20",
                "--dest",
                str(dest.parent),
                url,
            ]
        )
        if rc == 0 and _is_valid_wheel(dest):
            print(f"[spacy-model] download ok (attempt {attempt}/{attempts})", flush=True)
            return True
        if attempt < attempts:
            delay = backoff_base * (2 ** (attempt - 1))
            print(
                f"[spacy-model] attempt {attempt}/{attempts} failed (rc={rc}); retry in {delay:.0f}s",
                flush=True,
            )
            time.sleep(delay)
    return False


def _verify_import(model: str) -> bool:
    """装完必须真 import 一次：能 import 才代表模型包与 dist-info 都在。"""
    code = (
        "import importlib\n"
        f"m = importlib.import_module({model!r})\n"
        "import spacy\n"
        f"print('[spacy-model] import ok:', m.__file__, 'spacy', spacy.__version__)\n"
    )
    return _run([sys.executable, "-c", code]) == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安装 spaCy 德语模型（缓存优先 + 有界重试）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument("--cache-dir", default=".spacy-wheel-cache")
    parser.add_argument("--attempts", type=int, default=3, help="下载尝试次数上限（有界）")
    parser.add_argument("--backoff-base", type=float, default=15.0, help="指数退避基数（秒）")
    # 仅供本地验证重试逻辑：指向坏 URL 复现「重试耗尽 ⇒ 响亮失败」。
    parser.add_argument("--url", default=None, help="覆盖下载 URL（测试钩子，CI 不传）")
    args = parser.parse_args(argv)

    attempts = max(1, args.attempts)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = _wheel_path(cache_dir, args.model, args.version)

    if _is_valid_wheel(dest):
        print(f"[spacy-model] cache-hit=yes wheel={dest}", flush=True)
    else:
        print(f"[spacy-model] cache-hit=no wheel={dest}", flush=True)
        url = args.url or _wheel_url(args.model, args.version)
        if not _download(url, dest, attempts, args.backoff_base):
            print(
                f"::error::spaCy 模型下载失败：{args.model}-{args.version} 在 {attempts} 次"
                f"尝试（含指数退避）后仍不可用；来源 {url}。拒绝静默跳过。",
                file=sys.stderr,
                flush=True,
            )
            return 1

    rc = _run([sys.executable, "-m", "pip", "install", "--no-deps", str(dest)])
    if rc != 0:
        print(f"::error::本地 wheel 安装失败（rc={rc}）：{dest}", file=sys.stderr, flush=True)
        return 1

    if not _verify_import(args.model):
        print(f"::error::模型已安装但 import 失败：{args.model}", file=sys.stderr, flush=True)
        return 1

    print(f"[spacy-model] ready: {args.model}-{args.version}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
