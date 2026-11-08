# -*- coding: utf-8 -*-
"""tools/build_css.py —— 按清单顺序拼接 src/css/*.css，无损生成 static/style.css。

设计契约（与 tools/build_index_html.py 同型，但更严）：
1. 纯 Python 标准库驱动，无第三方依赖；
2. `SOURCE_FILES` 是**唯一顺序事实来源**；目录里出现未登记 .css ⇒ 直接失败，
   防止「新加的分片永远不参与构建」这类静默漂移；
3. 逐文件按**原始字节**读取并拼接，不做换行归一化、不做编码转换 —— 拆分前后
   `static/style.css` 的 sha256 必须字节一致，这是本脚本的验收标准；
4. `--check` 只比对不写盘，供同步闸与本地预检使用。
"""

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_SOURCE_DIR = ROOT / "src" / "css"
OUTPUT_PATH = ROOT / "static" / "style.css"

# 顺序 = 原 style.css 的行序。任何调整都等价于级联顺序变更，MUST 先过视觉基线。
SOURCE_FILES = (
    "01-tokens-base.css",
    "02-home-views.css",
    "03-reader.css",
    "04-drawer-wordcard.css",
    "05-cards-player.css",
    "06-deck-exam.css",
    "07-progress-quiz.css",
    "08-settings-writer.css",
    "09-a1-encounter-companion-overrides.css",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def assemble_css(source_dir: Path = CSS_SOURCE_DIR) -> bytes:
    """按 SOURCE_FILES 顺序拼接源码，返回原始字节。"""
    if not source_dir.is_dir():
        _fail(f"CSS 源码目录缺失: {source_dir}")

    present = {path.name for path in source_dir.glob("*.css")}
    missing = [name for name in SOURCE_FILES if name not in present]
    if missing:
        _fail(f"缺少已登记的分片: {', '.join(missing)}")

    unlisted = sorted(present - set(SOURCE_FILES))
    if unlisted:
        _fail(
            "src/css 下存在未登记的分片（不会参与构建，MUST 显式加入 SOURCE_FILES）: "
            + ", ".join(unlisted)
        )

    chunks = []
    for name in SOURCE_FILES:
        chunk = (source_dir / name).read_bytes()
        if not chunk:
            _fail(f"分片为空: {name}")
        try:
            chunk.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail(f"分片不是合法 UTF-8: {name} ({exc})")
        chunks.append(chunk)

    return b"".join(chunks)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pin_utf8_streams() -> None:
    """把 stdout/stderr 的写侧钉死为 UTF-8（同 build_index_html.py 的加固）。"""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # silent-ok: 仅显示层编码（流不可重配置）⇒ 保持原流；结论由退出码表达
                pass


def main() -> int:
    _pin_utf8_streams()
    parser = argparse.ArgumentParser(description="拼接 src/css 生成 static/style.css")
    parser.add_argument("--check", action="store_true", help="校验模式：仅检查产物是否与源码拼接结果一致")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="输出文件路径")
    args = parser.parse_args()

    try:
        assembled = assemble_css()
    except Exception as exc:
        print(f"[build_css] 错误: {exc}", file=sys.stderr)
        return 1

    out_file = Path(args.output)
    expected_hash = sha256_hex(assembled)

    if args.check:
        if not out_file.exists():
            print(f"[build_css] 目标文件缺失: {out_file}", file=sys.stderr)
            return 1
        current = out_file.read_bytes()
        if current != assembled:
            print(
                "[build_css] static/style.css 与 src/css 拼接结果存在漂移！"
                "请先修改 src/css 分片，再运行 python tools/build_css.py 重新生成。"
                f"（源码 sha256={expected_hash}，产物 sha256={sha256_hex(current)}）",
                file=sys.stderr,
            )
            return 1
        print(f"[build_css] 校验通过：产物与源码逐字节一致 (sha256={expected_hash})。")
        return 0

    out_file.write_bytes(assembled)
    line_count = assembled.count(b"\n")
    print(f"[build_css] 成功生成: {out_file} ({line_count} 行, sha256={expected_hash})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
