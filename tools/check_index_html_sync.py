# -*- coding: utf-8 -*-
"""tools/check_index_html_sync.py —— 机械门禁：校验 static/index.html 与模板装配物一致性。

作为 CI 与本地质量门禁的一部分，若开发者手动编辑了 static/index.html 或片段文件却未同步，
本脚本将打印统一 diff 并退出码 1，杜绝分块与单体产物漂移。
"""

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from build_index_html import INDEX_PATH, SKELETON_PATH, assemble_index_html  # noqa: E402


def _pin_utf8_streams() -> None:
    """把 stdout/stderr 的**写侧**钉死为 UTF-8（写法沿用 start.py 的既有加固）。

    为什么需要：本脚本 print 中文结论。若写侧跟随终端 locale（GitHub Windows runner
    = cp1252，本机 = GBK），调用方（`pytest` 的 subprocess）按 UTF-8 读取就会解码失败；
    而失败发生在 subprocess 的读线程内，不体现在 returncode 上，表现为「退出码 0 但
    stdout 为 None」的假绿/假红。写侧固定后，读侧再显式 encoding="utf-8" 才能闭环。
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # silent-ok: 仅显示层编码（流不可重配置）⇒ 保持原流；本闸结论由退出码表达
                pass


def main() -> int:
    _pin_utf8_streams()
    if not SKELETON_PATH.exists():
        # 过渡期保护：若尚未建立 skeleton，静态单体本身即为真相源，直接放行
        print("[check_index_html_sync] 提示: static/index.skeleton.html 尚未创建，处于单体过渡态，检查放行。")
        return 0

    if not INDEX_PATH.exists():
        print(f"[check_index_html_sync] 错误: {INDEX_PATH} 缺失！", file=sys.stderr)
        return 1

    try:
        expected = assemble_index_html(SKELETON_PATH)
    except Exception as exc:
        print(f"[check_index_html_sync] 模板解析失败: {exc}", file=sys.stderr)
        return 1

    actual = INDEX_PATH.read_text(encoding="utf-8")

    expected_lines = expected.replace("\r\n", "\n").splitlines(keepends=True)
    actual_lines = actual.replace("\r\n", "\n").splitlines(keepends=True)

    if expected_lines != actual_lines:
        diff = difflib.unified_diff(
            actual_lines,
            expected_lines,
            fromfile="static/index.html (current on disk)",
            tofile="static/index.html (assembled from templates)",
            n=3,
        )
        print("[check_index_html_sync] FAIL: static/index.html 与模板片段装配产物不一致！", file=sys.stderr)
        print("请运行 `python tools/build_index_html.py` 重新装配后再提交。\n", file=sys.stderr)
        sys.stderr.writelines(diff)
        return 1

    print("[check_index_html_sync] PASS: static/index.html 与分块模板 100% 同步 (sha256 契约一致)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
