#!/usr/bin/env python3
"""
DeLector - Windows Portable Packager
Builds a standalone, zero-dependency Windows portable distribution.
"""

import os
import shutil
import subprocess
import sys
from typing import List, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── 验包自检：产物必须含 WebView2 运行时 DLL ─────────────────────────────────
# pywebview 走系统 Edge WebView2；漏收这两个 DLL，exe 能起、窗口却**白屏**（无报错弹窗）
# —— 与 v4.8.1（routes_corpus 漏登记） / v5.2.0（routes_rtc/exam 漏登记）同款的
# "本地全绿、打包后静默失败"。故构建后**硬自检**，缺失即非零退出。
REQUIRED_WEBVIEW2_DLL_NEEDLES: Tuple[str, ...] = (
    "WebView2Loader.dll",
    "Microsoft.Web.WebView2",
)


def verify_webview2_payload(release_dir: str) -> List[str]:
    """递归扫描产物目录，返回**缺失**的 WebView2 DLL 清单（空清单 = 通过）。

    大小写不敏感（Windows 文件名大小写不固定）；递归（DLL 落在 `_internal/webview/lib/`
    之类的子目录，只扫顶层会漏判 ⇒ 白屏包被放行）。
    """
    names: List[str] = []
    for _dirpath, _dirnames, filenames in os.walk(release_dir):
        names.extend(name.lower() for name in filenames)
    # MUST 锚定 `.dll` 后缀：产物同目录常伴 `Microsoft.Web.WebView2.Core.xml`/`.pdb`（同名却非 DLL），
    # 只做子串匹配会被这些同伴文件名命中 ⇒ 真漏收 DLL 却**假绿**，白屏包照样发布。
    return [
        needle
        for needle in REQUIRED_WEBVIEW2_DLL_NEEDLES
        if not any(name.endswith(".dll") and needle.lower() in name for name in names)
    ]


def assert_webview2_payload(release_dir: str) -> None:
    """缺 DLL ⇒ 打印缺失清单并**非零退出**（构建失败），绝不只打印警告就放行。"""
    missing = verify_webview2_payload(release_dir)
    if not missing:
        return
    print("[Error] 打包产物缺少 WebView2 运行时 DLL ⇒ 解压后双击会**白屏**（窗口起不来、无报错）：")
    for name in missing:
        print(f"    - {name}")
    print("        这与 v4.8.1 / v5.2.0 的漏模块事故同款：本地全绿、打包后静默失败。")
    sys.exit(1)


def release_readme(version: str) -> str:
    """产物内《说明_README.txt》正文（入口的**单一文案真相**）。

    为什么抽成纯函数：入口从"起服务 + 开默认浏览器"改为"打开桌面窗口"后，文案若不同步，用户会照着
    README 找一个已不存在的启动方式 —— 属"文档漂移"类静默失败。抽出来后守卫测试可直接断言文本
    （tests/test_server.py::test_windows_portable_readme_matches_desktop_entry）。
    """
    return f"""# DeLector — 德语学术精读与备考工作台 ({version} 绿色便携版)

## 🚀 启动方式
直接双击运行 `DeLector.exe` ⇒ 打开**桌面窗口**（原生窗口，无需浏览器）。

## ⚙️ API 配置 (可选)
软件内置 0ms 德语核心词库、形态学三态表、复合词拆解、五场域拓扑与从句树分析，全部 100% 离线运行。
如需使用 DeepSeek 深度 AI 考点剖析，在页面右上角点击「⚙️ 设置」填入 API Key 即可。

## 📱 手机 / 平板局域网伴读（旧工作流）
需要手机 / 平板在**同一 Wi-Fi** 下访问工作台 ⇒ 运行 `DeLector.exe --server-only`：
它会打印局域网地址（例如 `http://192.168.x.x:8000`），在手机浏览器打开该地址即可同步阅读。
"""


def build_windows() -> None:
    version = os.environ.get("GITHUB_REF_NAME", "v3.8.0")
    print("=" * 60)
    print(f"  DeLector {version} -- Windows Portable Packager")
    print("=" * 60)

    root_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")

    # 1. Clean previous build artifacts
    for d in [os.path.join(dist_dir, "DeLector"), build_dir]:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
            except Exception as e:
                print(f"[Warn] Could not delete {d}: {e}")

    # 2. Build PyInstaller command
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name=DeLector",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--console",  # Keep console so user sees service logs & IP addresses
        f"--add-data={os.path.join(root_dir, 'static')}{os.pathsep}static",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=delector.data.core_dict",
        "--hidden-import=delector.data.core_dict_ext",
        "--hidden-import=delector.data.prep_dict",
        "--hidden-import=delector.data.a1_dict",
        "--hidden-import=delector.data.a1_writing_dict",
        "--hidden-import=delector.data.a1_hoeren_dict",
        "--hidden-import=delector.data.a1_lesen_dict",
        "--hidden-import=delector.data.corpus_dict",
        "--hidden-import=delector.data.encounter_seed_dict",
        "--hidden-import=delector.data.a1_workbench_dict",
        # R8 交付 1：本分支新增两片（official_vocab 官方词表分片 + lexicon_merge
        # 字段级合并共享纯函数），均住 delector/data/，与其它数据模块同口径逐条注册。
        "--hidden-import=delector.data.official_vocab",
        "--hidden-import=delector.data.lexicon_merge",
        # Phase 2 · S1：富字段 side-car 分片（ipa/例句），与其它数据模块同口径逐条注册。
        "--hidden-import=delector.data.official_vocab_rich",
        "--hidden-import=delector.data.a1_fragments",
        "--hidden-import=delector.data.a1_sidecar",
        "--hidden-import=delector.routes.a1",
        "--hidden-import=delector.routes.a2",
        "--hidden-import=delector.routes.a1_hoeren",
        "--hidden-import=delector.routes.a1_lesen",
        "--hidden-import=delector.routes.corpus",
        "--hidden-import=delector.routes.sync",
        "--hidden-import=delector.routes.rtc",
        "--hidden-import=delector.routes.exam",
        "--hidden-import=delector.routes.listen",
        "--hidden-import=delector.routes.syntax_hard",
        "--hidden-import=delector.routes.main",
        "--hidden-import=delector.routes.tools",
        "--hidden-import=delector.services.writing",
        "--hidden-import=delector.services.essay_diff",
        "--hidden-import=delector.services.exam_catalog",
        "--hidden-import=delector.services.tts",
        "--hidden-import=delector.services.listen",
        "--hidden-import=delector.services.syntax_score",
        "--hidden-import=de_core_news_sm",
        "--hidden-import=spacy.lang.de",
        "--hidden-import=genanki",
        "--hidden-import=edge_tts",
        "--hidden-import=httpx",
        "--collect-all=de_core_news_sm",
        "--collect-all=spacy",
        # Windows 桌面壳冻结项（ADR-0020 §3.1，按 pywebview 官方 PyInstaller 建议）：
        # pywebview 走系统 Edge WebView2，必须整包收集 webview 及其 Windows 后端，
        # 否则冻结后 import 失败 / 窗口白屏（本地 pytest 全绿）。
        "--collect-all=webview",
        "--hidden-import=webview.platforms.edgechromium",
        "--hidden-import=webview.platforms.winforms",
        "--hidden-import=pystray._win32",
        os.path.join(root_dir, "desktop.py"),
    ]

    print("\n[1/3] 正在编译二进制可执行程序并收集依赖与 spaCy 语言模型...")
    result = subprocess.run(pyinstaller_cmd, cwd=root_dir)
    if result.returncode != 0:
        print("[Error] PyInstaller 打包失败！")
        sys.exit(result.returncode)

    # 3. Assemble Portable Release Directory
    release_name = f"DeLector-{version}-Windows-x64-Portable"
    release_dir = os.path.join(dist_dir, release_name)
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)

    built_output = os.path.join(dist_dir, "DeLector")
    if os.path.exists(built_output):
        shutil.move(built_output, release_dir)

    # 4. 验包：产物必须含 WebView2 运行时 DLL（缺 ⇒ 解压后白屏）。硬失败，非警告。
    assert_webview2_payload(release_dir)

    # 5. Copy helper files（文案与入口同源：见 release_readme 的单一真相说明）
    with open(os.path.join(release_dir, "说明_README.txt"), "w", encoding="utf-8") as f:
        f.write(release_readme(version))

    print("\n" + "=" * 60)
    print("[SUCCESS] 绿色便携版打包成功！")
    print(f"发布包目录: {release_dir}")
    print(f"可执行程序: {os.path.join(release_dir, 'DeLector.exe')}")
    print("=" * 60)


if __name__ == "__main__":
    build_windows()
