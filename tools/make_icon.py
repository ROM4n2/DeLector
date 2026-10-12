#!/usr/bin/env python
"""生成启动器图标：Android `ic_launcher`（各 mipmap 密度）+ Windows `assets/DeLector.ico`。

用法：
  python tools/make_icon.py                     # Android 五档 ic_launcher（默认 "De" 字标）
  python tools/make_icon.py --windows           # 追加生成 Windows 的 assets/DeLector.ico
  python tools/make_icon.py --source 图.png     # 用你自己的图（Android + 可配 --windows）

为什么一个脚本管两端：图标是**同一枚品牌**，Android 要 mipmap 的 PNG 五档、Windows 的
PyInstaller `--icon` 要 .ico（16/32/48/256 多尺寸）。分成两个脚本 ⇒ 换品牌时要改两处，
两端图标必然对不上（本仓"两份副本必漂移"的同族教训）。渲染函数 `_render_icon` 两处共用。

为什么有默认占位：manifest 一旦引用 @mipmap/ic_launcher，mipmap 文件必须存在，
否则 CI 构建直接失败。占位图标 = 与 PWA manifest 一致的 "De" 字标（深底赭红）。
换图标 = 放一张图 → 重跑本脚本（--windows 一并生效）→ 触发 CI 重打包。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
RES_DIR = REPO_ROOT / "android" / "app" / "src" / "main" / "res"
ASSETS_DIR = REPO_ROOT / "assets"

# 密度 → 图标边长(px)，Android 启动器标准
DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

# Windows：PyInstaller `--icon` 只吃 .ico，且任务栏/资源管理器按容器里的多尺寸取用
# （缺 16/32 会在小尺寸场景被放大糊掉）。
WINDOWS_ICO_SIZES: tuple[int, ...] = (16, 32, 48, 256)


def _draw_default_icon(size: int) -> Image.Image:
    """品牌默认图标：深色圆角方底 + 衬线 "De"（赭红）。无 --source 时的占位。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    # 深底圆角矩形（含轻微内边距，留出圆角外的透明区）
    d.rounded_rectangle(
        [int(size * 0.04), int(size * 0.04), int(size * 0.96), int(size * 0.96)],
        radius=radius,
        fill=(26, 23, 20, 255),  # #1a1714
    )
    # 找衬线字体：优先系统可用，退到默认
    # 注解取 Any：types-Pillow 里 FreeTypeFont 与 ImageFont 的继承关系与实际不符
    # （truetype 返回 FreeTypeFont、load_default 返回 ImageFont，stub 判二者不可互换）
    font: Any = None
    for path in ("C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/georgiab.ttf", "C:/Windows/Fonts/arial.ttf"):
        p = Path(path)
        if p.exists():
            font = ImageFont.truetype(str(p), int(size * 0.5))
            break
    if font is None:
        font = ImageFont.load_default()
    text = "De"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]), text, font=font, fill=(200, 75, 49, 255))  # #c84b31
    return img


def _render_icon(px: int, source_img: Image.Image | None) -> Image.Image:
    """按边长渲染一枚图标：有 `--source` 用其居中裁方，否则用品牌默认 "De" 字标。

    Android 与 Windows 两端共用这一枚 —— 换品牌只改 `_draw_default_icon` 一处。
    """
    if source_img is not None:
        # Pillow ≥ 9.1 把重采样常量移到 Image.Resampling（顶层别名已废弃，stub 只认新路径）
        return _center_square(source_img).resize((px, px), Image.Resampling.LANCZOS)
    return _draw_default_icon(px)


def _center_square(img: Image.Image) -> Image.Image:
    """居中裁成正方形（取较短边），放大不失真。"""
    w, h = img.size
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    return img.crop((left, top, left + s, top + s))


def main() -> None:
    parser = argparse.ArgumentParser(description="生成启动器图标（Android mipmap + Windows .ico）")
    parser.add_argument(
        "--source", type=str, default="", help="用户图片路径（PNG/JPG 等 Pillow 支持的格式；无则生成默认 De 字标）"
    )
    parser.add_argument(
        "--windows",
        action="store_true",
        help=f"追加生成 Windows 的 assets/DeLector.ico（{WINDOWS_ICO_SIZES}，供 PyInstaller --icon 用）",
    )
    args = parser.parse_args()

    source_img: Image.Image | None = None
    if args.source:
        src = Path(args.source)
        if not src.exists():
            raise SystemExit(f"源图不存在: {src}")
        source_img = Image.open(src).convert("RGBA")

    for density, px in DENSITIES.items():
        out_dir = RES_DIR / f"mipmap-{density}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "ic_launcher.png"
        _render_icon(px, source_img).save(out, format="PNG")
        print(f"  {out.relative_to(REPO_ROOT)}  ({px}x{px})")

    print(f"\n已生成 {len(DENSITIES)} 个密度的 ic_launcher.png。")
    print("确认 AndroidManifest.xml 的 android:icon/roundIcon 指向 @mipmap/ic_launcher。")

    if args.windows:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        ico = ASSETS_DIR / "DeLector.ico"
        # 基准取最大尺寸再由 Pillow 重采样生成各档，避免小尺寸下圆角/字形被独立渲染出差异
        _render_icon(max(WINDOWS_ICO_SIZES), source_img).save(
            ico, format="ICO", sizes=[(s, s) for s in WINDOWS_ICO_SIZES]
        )
        print(f"  {ico.relative_to(REPO_ROOT)}  (sizes={list(WINDOWS_ICO_SIZES)})")
        print("确认 package_windows.py 的 `--icon=` 指向该文件。")
    else:
        print("（未生成 Windows .ico：需要时加 `--windows`）")

    print("重打包：GitHub Actions → workflow_dispatch 触发即可（本机无需 Android SDK）。")
    print("换图：放一张图 → python tools/make_icon.py --source 图.png [--windows] → 重打包。")


if __name__ == "__main__":
    main()
