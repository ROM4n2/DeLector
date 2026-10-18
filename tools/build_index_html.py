# -*- coding: utf-8 -*-
"""tools/build_index_html.py —— 基于骨架和子模块无损装配 static/index.html。

设计契约：
1. 纯 Python 标准库驱动，无第三方依赖；
2. 骨架文件默认为 static/index.skeleton.html（如果不存在则以静态 index.html 为基准）；
3. 占位符契约：严格识别 `<!-- @include: path/to/file.html -->`，并将目标片段内容逐字插回；
4. 换行与编码：统一规范为 CRLF 换行输出，确保与全仓 UTF-8 CRLF 卫生契约一致。
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKELETON_PATH = ROOT / "static" / "index.skeleton.html"
INDEX_PATH = ROOT / "static" / "index.html"
INCLUDE_RE = re.compile(r"<!--\s*@include:\s*([^\s>]+)\s*-->")


def assemble_index_html(skeleton_file: Path = SKELETON_PATH) -> str:
    """从骨架文件解析并递归/单层拼接所有 include 片段。"""
    if not skeleton_file.exists():
        # 兼容过渡期：如果尚未建立 skeleton，直接读取既有 index.html
        if INDEX_PATH.exists():
            return INDEX_PATH.read_text(encoding="utf-8")
        raise FileNotFoundError(f"缺少骨架文件或目标文件: {skeleton_file}")

    skeleton_content = skeleton_file.read_text(encoding="utf-8")
    static_dir = ROOT / "static"

    def _replace_include(match: re.Match[str]) -> str:
        rel_include = match.group(1).strip()
        include_path = static_dir / rel_include
        if not include_path.exists():
            raise FileNotFoundError(f"找不到 include 片段文件: {rel_include} (绝对路径: {include_path})")
        # 递归支持嵌套包含
        return assemble_index_html(include_path)

    assembled = INCLUDE_RE.sub(_replace_include, skeleton_content)
    # 统一确保换行符是 CRLF
    normalized = assembled.replace("\r\n", "\n").replace("\n", "\r\n")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="装配 static/index.html")
    parser.add_argument("--check", action="store_true", help="校验模式：仅检查 index.html 是否与装配结果一致")
    parser.add_argument("--output", type=str, default=str(INDEX_PATH), help="输出文件路径")
    args = parser.parse_args()

    try:
        assembled = assemble_index_html()
    except Exception as exc:
        print(f"[build_index_html] 错误: {exc}", file=sys.stderr)
        return 1

    out_file = Path(args.output)
    if args.check:
        if not out_file.exists():
            print(f"[build_index_html] 目标文件缺失: {out_file}", file=sys.stderr)
            return 1
        current = out_file.read_text(encoding="utf-8")
        current_norm = "".join(current.splitlines(keepends=True))
        assembled_norm = "".join(assembled.splitlines(keepends=True))
        if current_norm != assembled_norm:
            print(
                "[build_index_html] static/index.html 与模板装配结果存在漂移！"
                "请运行 python tools/build_index_html.py 重新生成。",
                file=sys.stderr,
            )
            return 1
        print("[build_index_html] 校验通过：static/index.html 与模板骨架 100% 同步。")
        return 0

    out_file.write_text(assembled, encoding="utf-8", newline="")
    print(f"[build_index_html] 成功生成: {out_file} ({len(assembled.splitlines())} 行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
