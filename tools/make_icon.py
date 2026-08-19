#!/usr/bin/env python
"""生成 Android 启动器图标（ic_launcher）到各 mipmap 密度目录。

用法：
  python tools/make_icon.py --source path/to/图.png   # 用你自己的图生成
  python tools/make_icon.py                            # 无 --source 时生成默认 "De" 字标占位

原理：把源图居中裁成正方形 → 缩放输出到 mipmap-mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi
（48/72/96/144/192px）。AndroidManifest 的 android:icon 指向 @mipmap/ic_launcher，
重建 APK 走 CI（GitHub Actions workflow_dispatch），本机无需 Android SDK。

为什么有默认占位：manifest 一旦引用 @mipmap/ic_launcher，mipmap 文件必须存在，
否则 CI 构建直接失败。占位图标 = 与 PWA manifest 一致的 "De" 字标（深底赭红）。
换图标 = 放一张图 → 重跑本脚本 → 触发 CI 重打包。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
RES_DIR = REPO_ROOT / "android" / "app" / "src" / "main" / "res"

# 密度 → 图标边长(px)，Android 启动器标准
DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}


def _draw_default_icon(size: int) -> Image.Image:
    """品牌默认图标：深色圆角方底 + 衬线 "De"（赭红）。无 --source 时的占位。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    # 深底圆角矩形（含轻微内边距，留出圆角外的透明区）
    d.rounded_rectangle(
        [int(size * 0.04), int(size * 0.04), int(size * 0.96), int(size * 0.96)],
        radius=radius, fill=(26, 23, 20, 255),  # #1a1714
    )
    # 找衬线字体：优先系统可用，退到默认
    font = None
    for path in ("C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/georgiab.ttf",
                 "C:/Windows/Fonts/arial.ttf"):
        p = Path(path)
        if p.exists():
            font = ImageFont.truetype(str(p), int(size * 0.5))
            break
    if font is None:
        font = ImageFont.load_default()
    text = "De"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1]),
           text, font=font, fill=(200, 75, 49, 255))  # #c84b31
    return img


def _center_square(img: Image.Image) -> Image.Image:
    """居中裁成正方形（取较短边），放大不失真。"""
    w, h = img.size
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    return img.crop((left, top, left + s, top + s))


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Android 启动器图标（ic_launcher）")
    parser.add_argument("--source", type=str, default="",
                        help="用户图片路径（PNG/JPG/SVG 由 Pillow 支持；无则生成默认 De 字标）")
    args = parser.parse_args()

    source_img: Image.Image | None = None
    if args.source:
        src = Path(args.source)
        if not src.exists():
            raise SystemExit(f"源图不存在: {src}")
        source_img = Image.open(src).convert("RGBA")

    for density, px in DENSITIES.items():
        if source_img is not None:
            icon = _center_square(source_img).resize((px, px), Image.LANCZOS)
        else:
            icon = _draw_default_icon(px)
        out_dir = RES_DIR / f"mipmap-{density}"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "ic_launcher.png"
        icon.save(out, format="PNG")
        print(f"  {out.relative_to(REPO_ROOT)}  ({px}x{px})")

    print(f"\n已生成 {len(DENSITIES)} 个密度的 ic_launcher.png。")
    print("确认 AndroidManifest.xml 的 android:icon/roundIcon 指向 @mipmap/ic_launcher。")
    print("重打包：GitHub Actions → workflow_dispatch 触发即可（本机无需 Android SDK）。")
    print("换图：放一张图 → python tools/make_icon.py --source 图.png → 重打包。")


if __name__ == "__main__":
    main()
