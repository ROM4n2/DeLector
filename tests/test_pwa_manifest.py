# -*- coding: utf-8 -*-
"""PWA manifest 与图标资产契约。

回归背景：manifest 曾把同一份内联 SVG 同时声明为 ``192x192 512x512``，
Chrome/Android 安装提示要求可解码的 192 与 512 位图，导致安装图标规格不达标。
"""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
MANIFEST = STATIC / "manifest.json"


def _icons() -> list[dict]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["icons"]


def test_manifest_has_192_and_512_png_icons():
    """至少提供 192x192 与 512x512 的 PNG 位图（安装提示硬性要求）。"""
    entries = [i for i in _icons() if i["type"] == "image/png"]
    declared = {i["sizes"] for i in entries}
    assert {"192x192", "512x512"} <= declared, f"缺少 PNG 尺寸声明: {declared}"

    for icon in entries:
        path = STATIC / icon["src"]
        assert path.is_file(), f"图标文件缺失: {path}"
        with Image.open(path) as img:
            assert img.size == _parse_size(icon["sizes"]), f"{path} 实际尺寸 {img.size} 与声明不符"


def test_manifest_icon_paths_are_root_relative():
    """静态目录挂在站点根（server.py: StaticFiles(directory=STATIC_DIR)），
    manifest 的 src 不能带 /static 前缀，否则安装时图标 404。"""
    for icon in _icons():
        src = icon["src"]
        if src.startswith("data:"):
            continue
        assert not src.startswith(("/", "static/")), f"图标路径应为根相对: {src}"


def _parse_size(token: str) -> tuple[int, int]:
    w, h = token.split("x")
    return int(w), int(h)
