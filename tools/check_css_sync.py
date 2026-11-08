# -*- coding: utf-8 -*-
"""tools/check_css_sync.py —— 机械门禁：校验 static/style.css 与 src/css 分片拼接物一致。

零差异拆分的核心约束是「源码是唯一真相，产物只是拼接结果」。若有人直接编辑
`static/style.css` 而没改分片，下一次构建会静默覆盖他的改动；本闸在 CI 与本地
预检里把这类漂移判红，并打印统一 diff。

与 `check_index_html_sync.py` 的差异：这里 MUST 按**原始字节**比较（不做 CRLF→LF
归一化），因为拆分阶段的验收标准就是 sha256 字节一致；归一化会把「行尾被改」
这类真实漂移吃掉。
"""

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from build_css import OUTPUT_PATH, assemble_css, sha256_hex  # noqa: E402


def _pin_utf8_streams() -> None:
    """把 stdout/stderr 的写侧钉死为 UTF-8（理由见 check_index_html_sync.py）。"""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # silent-ok: 仅显示层编码（流不可重配置）⇒ 保持原流；本闸结论由退出码表达
                pass


def main() -> int:
    _pin_utf8_streams()
    parser = argparse.ArgumentParser(description="校验 static/style.css 与 src/css 拼接物一致")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="待校验的产物路径")
    args = parser.parse_args()
    target = Path(args.output)

    if not target.exists():
        print(f"[check_css_sync] 错误: {target} 缺失！", file=sys.stderr)
        return 1

    try:
        expected = assemble_css()
    except Exception as exc:
        print(f"[check_css_sync] 源码拼接失败: {exc}", file=sys.stderr)
        return 1

    actual = target.read_bytes()
    if expected != actual:
        print(
            "[check_css_sync] FAIL: static/style.css 与 src/css 分片拼接产物不一致！\n"
            f"源码 sha256={sha256_hex(expected)}\n产物 sha256={sha256_hex(actual)}",
            file=sys.stderr,
        )
        print("请先修改 src/css 分片，再运行 `python tools/build_css.py` 重新生成后提交。\n", file=sys.stderr)
        expected_lines = expected.decode("utf-8", errors="replace").splitlines(keepends=True)
        actual_lines = actual.decode("utf-8", errors="replace").splitlines(keepends=True)
        sys.stderr.writelines(
            difflib.unified_diff(
                actual_lines,
                expected_lines,
                fromfile="static/style.css (current on disk)",
                tofile="static/style.css (assembled from src/css)",
                n=3,
            )
        )
        return 1

    print(
        "[check_css_sync] PASS: static/style.css 与 src/css 分片逐字节同步 "
        f"(sha256={sha256_hex(actual)})。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
