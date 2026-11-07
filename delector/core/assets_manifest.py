# -*- coding: utf-8 -*-
"""静态资源内容指纹：构建期（Android/桌面打包）与运行期（/api/health）共用一套算法。

为什么需要它：版本号（``APP_VERSION`` / Android ``versionCode``）只在**手动 bump**
时变化，而 CSS/JS 改动并不必然伴随版本号变化。于是「装的是哪一版前端」在设备上
不可观测，验证新代码时很容易拿旧资源得出错误结论（v4.4.5 同族事故）。

本模块给出一枚**随静态文件内容变化**的短指纹，并要求两道闸门都用它：

1. 打包时写进 ``static/asset-fingerprint.txt`` 与页面 ``<meta name="delector-assets">``；
2. 运行时 ``/api/health`` 现算磁盘上的指纹。

页面把「构建时随 HTML 一起落地的指纹」与「服务端当前磁盘指纹」放在一起比较：
不相等 ⇒ 页面拿到的是旧资源，无需清任何缓存即可判定。

纪律：本模块是**叶模块**，只吃标准库（同 ``delector/core/version.py``），
``tools/`` 下的构建脚本可直接按路径加载它。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Iterator, Tuple

__all__ = [
    "ASSET_STAMP_META_NAME",
    "JS_STAMP_REL_PATH",
    "compute_assets_fingerprint",
    "inject_js_stamp",
    "inject_stamp_meta",
    "iter_asset_files",
]

#: 页面侧构建戳的 meta 名称（页面用 document.querySelector 读取）。
ASSET_STAMP_META_NAME = "delector-assets"

#: 承载 JS 构建戳的模块（相对 static 的路径）。
JS_STAMP_REL_PATH = "js/build-stamp.js"

#: 指纹自身的落盘文件不参与哈希，否则写一次指纹就改变一次指纹。
#: 同时兼容历史点文件名，避免旧产物参与哈希后指纹漂移。
_IGNORED_NAMES = frozenset(
    {".asset-fingerprint", "asset-fingerprint.txt", ".build-info.json", "build-info.json"}
)

# 归一化时整枚戳（含前导空白）直接删掉：仓库无戳、打包有戳，删完必须逐字节一致。
_STAMP_TAG_RE = re.compile(
    r'\s*<meta\s+[^>]*name=["\']' + ASSET_STAMP_META_NAME + r'["\'][^>]*>',
    re.IGNORECASE,
)
# 注入/覆盖时只替换 content 取值。
_STAMP_VALUE_RE = re.compile(
    r'(<meta\s+[^>]*name=["\']'
    + ASSET_STAMP_META_NAME
    + r'["\'][^>]*content=["\'])[^"\']*(["\'])',
    re.IGNORECASE,
)
_HEAD_RE = re.compile(rb"<head[^>]*>", re.IGNORECASE)
_JS_STAMP_RE = re.compile(
    r'(export\s+const\s+BUILD_STAMP\s*=\s*["\'])[^"\']*(["\'])'
)

# 磁盘快照 → 内容指纹。只缓存「快照没变」的情况，文件一改就重算。
_FINGERPRINT_CACHE: Dict[str, Tuple[str, str]] = {}


def iter_asset_files(static_dir: Path) -> Iterator[Tuple[Path, Path]]:
    """按相对路径排序产出 ``(相对路径, 绝对路径)``；跳过指纹自身文件。

    排序键 MUST 是 ``rel.as_posix()`` 而不是 ``Path`` 本身：Windows 上 ``sorted(Path)``
    按**大小写不敏感**比较（``icons/lucide-sprite.svg`` 会排在 ``icons/README.md``
    之前，POSIX 上恰好相反）。构建期在 Windows、运行期在 Android/Linux，一旦顺序不同
    同一份文件就会算出两枚指纹 —— 页面便永远报「服务端指纹不一致」（实测踩过：
    构建期 3061541188d7 / 设备运行期 cc1efb3c37f8）。
    """
    root = Path(static_dir)
    entries = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.name not in _IGNORED_NAMES
    ]
    for path in sorted(entries, key=lambda item: item.relative_to(root).as_posix()):
        yield path.relative_to(root), path


def _normalize_index_html(data: bytes) -> bytes:
    """删掉构建戳再算哈希。

    这样「仓库里的 index.html（无戳）」与「打包后注入过戳的 index.html」算出同一枚
    指纹，构建期与运行期不会因为戳的写法不同而互相误报；而 HTML 其余内容变化
    仍然会改变指纹。
    """
    text = data.decode("utf-8", errors="replace")
    return _STAMP_TAG_RE.sub("", text).encode("utf-8")


def _stat_key(root: Path) -> str:
    """廉价的目录快照：任一文件内容变化通常都会改变 size 或 mtime_ns。"""
    digest = hashlib.sha256()
    for rel, path in iter_asset_files(root):
        st = path.stat()
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(st.st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(st.st_mtime_ns).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def compute_assets_fingerprint(static_dir: Path, *, use_cache: bool = True) -> str:
    """返回 12 位十六进制内容指纹；目录不存在/不可读时返回空串。

    算法：按相对路径排序，逐个喂入 ``路径 + 长度 + 内容``；index.html 先做戳归一化。
    不用 ``mtime`` 作为最终指纹（打包工具会保留 mtime），只用它决定缓存是否失效。
    """
    root = Path(static_dir)
    if not root.is_dir():
        return ""
    try:
        key = _stat_key(root)
    except OSError:
        return ""
    cached = _FINGERPRINT_CACHE.get(str(root.resolve()))
    if use_cache and cached and cached[0] == key:
        return cached[1]

    digest = hashlib.sha256()
    count = 0
    try:
        for rel, path in iter_asset_files(root):
            data = path.read_bytes()
            rel_posix = rel.as_posix()
            if rel_posix == "index.html":
                data = _normalize_index_html(data)
            elif rel_posix == JS_STAMP_REL_PATH:
                # JS 戳随指纹写入；先抹平取值，避免「写戳 → 指纹变」的自指。
                text = data.decode("utf-8", errors="replace")
                data = _JS_STAMP_RE.sub(r"\1__DELECTOR_ASSETS__\2", text).encode("utf-8")
            digest.update(rel_posix.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(len(data)).encode("ascii"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
            count += 1
    except OSError:
        return ""
    digest.update(f"files={count}".encode("ascii"))
    fingerprint = digest.hexdigest()[:12]
    _FINGERPRINT_CACHE[str(root.resolve())] = (key, fingerprint)
    return fingerprint


def inject_stamp_meta(index_path: Path, fingerprint: str) -> None:
    """把构建戳写进 index.html 的 ``<head>``（已有则覆盖）。

    只改打包副本，不碰仓库源文件：源文件由模板装配闸（check_index_html_sync）守着，
    保持零漂移。
    """
    path = Path(index_path)
    # 按字节读写：Windows 上 read_text/write_text 的换行翻译会把整份 HTML 从 CRLF
    # 改成 LF，指纹随之漂移——那会把「写戳」本身变成一次资源变更。
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    stamp = f'<meta name="{ASSET_STAMP_META_NAME}" content="{fingerprint}" />'
    if _STAMP_VALUE_RE.search(text):
        text = _STAMP_VALUE_RE.sub(lambda m: m.group(1) + fingerprint + m.group(2), text)
    else:
        text_head = re.search(r"<head[^>]*>", text, re.IGNORECASE)
        insert_at = text_head.end() if text_head else len(text)
        prefix = "\n    " if text_head else "\n"
        text = text[:insert_at] + prefix + stamp + text[insert_at:]
    path.write_bytes(text.encode("utf-8"))


def inject_js_stamp(build_stamp_path: Path, fingerprint: str) -> None:
    """把构建戳写进 ``static/js/build-stamp.js`` 的 ``BUILD_STAMP``。

    页面会 import 这个常量并与 HTML 戳、服务端指纹三方比对：即使 HTML 已刷新、
    JS 仍被 HTTP/SW 缓存住，也能立即判定「跑的是旧 JS」。
    """
    path = Path(build_stamp_path)
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if not _JS_STAMP_RE.search(text):
        raise ValueError(f"{path} 缺少 export const BUILD_STAMP，无法注入构建戳")
    text = _JS_STAMP_RE.sub(lambda m: m.group(1) + fingerprint + m.group(2), text)
    path.write_bytes(text.encode("utf-8"))
