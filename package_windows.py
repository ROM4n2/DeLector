#!/usr/bin/env python3
"""
DeLector - Windows Portable Packager
Builds a standalone, zero-dependency Windows portable distribution.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Dict, List, Tuple

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


# ── 验包自检：产物不得夹带 .env（否则 API Key 随包发出去）─────────────────────────
# 便携版是"解压即用"，整包会被下载/转发给任何人。一旦构建目录里混进 `.env`
# （内含 DEEPSEEK_API_KEY 等），产物就会把 API Key 一起发出去 —— 与漏收 WebView2 DLL
# 同款的"本地全绿、打包后静默出事"，只是后果从白屏升级成**密钥泄露**。故构建后硬自检。
_ENV_FILE_SUFFIX = ".env"


def find_env_files(release_dir: str) -> List[str]:
    """递归扫描产物目录，返回**命中**的 .env 文件清单（相对产物根的路径，空清单 = 通过）。

    匹配 `.env` 与 `*.env` 两种变体（`endswith(".env")` 同时覆盖二者）：`prod.env` 这类
    改名同样会把 Key 带出去，不能只认裸 `.env`；大小写不敏感（Windows 文件名大小写不固定）。
    用 relpath 而非绝对路径：报错清单里不该出现构建机的私有目录结构。
    """
    hits: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(release_dir):
        hits.extend(
            os.path.relpath(os.path.join(dirpath, name), release_dir)
            for name in filenames
            if name.lower().endswith(_ENV_FILE_SUFFIX)
        )
    return sorted(hits)


def assert_no_env_in_payload(release_dir: str) -> None:
    """产物夹带 .env ⇒ 打印命中清单并**非零退出**（构建失败），绝不只打印警告就放行。"""
    leaked = find_env_files(release_dir)
    if not leaked:
        return
    print("[Error] 打包产物夹带了 .env ⇒ 解压后会把 API Key（如 DEEPSEEK_API_KEY）一起发给每个下载者：")
    for rel in leaked:
        print(f"    - {rel}")
    print("        请把 .env 挪出构建目录（.gitignore 已忽略它，但仍可能被人工复制进构建产物）。")
    sys.exit(1)


# ── 产物构建指纹 + 版本 fallback ─────────────────────────────────────────────
# 用户无法分辨自己双击的是哪个构建：本地不设 GITHUB_REF_NAME 时产物被命名成
# DeLector-v3.8.0-…（写死的误导名），而 App 实际是 v5.16.0 —— 排查中"以为是新包、
# 其实是旧包"白烧一轮。故在产物里写一份**机器可读**指纹 + README 顶一行人读指纹。
BUILD_INFO_FILENAME = ".build-info.json"
DEFAULT_ENTRY = "desktop.py"

# ── 预置文章预生成数据（子计划 2A）──────────────────────────────────────────────
# 数据文件的**仓库相对路径**（= 产物内相对路径）。用单一常量 + 字面量串表达，既作
# `--add-data` 的 src/dest，也让 `tests/test_server.py` 的打包守卫能对**同一字面量**做断言。
# 为什么 MUST 显式 --add-data：`--hidden-import` 只收 .py，收不到这个 .json；漏收不崩，但
# 运行时会静默降级成纯 Python 口径（「列表预览与详情跳变」复发），而本地 pytest 全绿。
PRESET_PROCESSED_DATA_REL = "delector/data/preset_processed.json"


# ── 版本号净化 + tag 语境判断 ─────────────────────────────────────────────────
# 为什么必须净化：GITHUB_REF_NAME 在 pull_request 事件里是 PR 合并引用名（形如 `128/merge`），
# 直接当版本会让产物目录嵌套成 dist/DeLector-128/merge-Windows-x64-Portable —— 构建步报
# "成功"、验包步（glob 只扫第一层）却找不到产物。同款脆弱点还会毁掉 build-release.yml 压缩步的
# Get-ChildItem -Filter（同样只扫第一层）。故：只在**真 tag 语境**才信任 GITHUB_REF_NAME，
# 且无论来源都做分隔符净化 + 硬失败断言。
_PATH_SEPARATORS: Tuple[str, ...] = ("/", "\\")


def tag_ref_name() -> str:
    """返回可当版本用的 CI 引用名；非 tag 语境 / 名不合法时返回空串（调用方回落 APP_VERSION）。

    GitHub 在 pull_request 事件里把 GITHUB_REF_NAME 设成 PR 合并引用名（`128/merge`），
    只有 GITHUB_REF_TYPE == "tag" 才是真发布 tag。缺 GITHUB_REF_TYPE 时（本地手工设变量）
    退化为"形如 v* 且不含路径分隔符"才采纳，兼顾本地可复现。
    """
    name = os.environ.get("GITHUB_REF_NAME", "")
    if not name:
        return ""
    ref_type = os.environ.get("GITHUB_REF_TYPE")
    if ref_type == "tag":
        return name
    if ref_type is None and _looks_like_release_tag(name):
        return name
    return ""


def _looks_like_release_tag(name: str) -> bool:
    """`name` 是否形如发布 tag（`v` 开头且不含路径分隔符）——GITHUB_REF_TYPE 缺失时的兜底判据。"""
    return name.startswith("v") and not any(sep in name for sep in _PATH_SEPARATORS)


def sanitize_version(raw: str) -> str:
    """把版本串里的路径分隔符替换为 '-'，避免产物目录被嵌套（`/` 与 `\\`）。"""
    version = raw
    for sep in _PATH_SEPARATORS:
        version = version.replace(sep, "-")
    return version


def assert_no_path_separator(version: str) -> None:
    """净化后仍含路径分隔符 ⇒ **非零退出**（构建期硬失败），绝不产出嵌套目录。

    为什么硬失败而非放行：嵌套产物会让下游验包 / 压缩步扫不到它（构建"成功"却没人能用），
    比直接红更危险——静默坏包。故构建期就炸，强制暴露。
    """
    offending = [sep for sep in _PATH_SEPARATORS if sep in version]
    if not offending:
        return
    print(f"[Error] 版本号仍含路径分隔符 {offending}：{version!r}")
    print("        这会把产物目录嵌套成 dist/<版本>/merge-…，验包 / 压缩步将扫不到它。")
    sys.exit(1)


def resolve_version() -> str:
    """发布版本号：仅在**真 tag 语境**取 CI 注入的 GITHUB_REF_NAME，否则回落 APP_VERSION。

    为什么必须区分 tag / branch 语境：GITHUB_REF_NAME 在 pull_request 事件里是 PR 合并
    引用名（`128/merge`），直接当版本会把产物目录嵌套成 dist/DeLector-128/merge-…，构建步
    报成功、验包却扫不到（只扫第一层）。GitHub 提供 GITHUB_REF_TYPE（`tag` / `branch`），
    只在 `tag` 时才信任该名（见 tag_ref_name）。
    保持既有语义：GITHUB_REF_TYPE=tag 且 GITHUB_REF_NAME=v5.16.0 ⇒ 版本仍是 `v5.16.0`。

    为什么必须回落 APP_VERSION 而非写死字面量：曾写死 'v3.8.0'，本地不设 GITHUB_REF_NAME
    时产物命名成 DeLector-v3.8.0-… 而 App 实为 v5.16.0，用户无从分辨。APP_VERSION 是应用级
    单一真相源（delector/core/version.py），此处只在前面补 'v'。
    """
    # 直接 import 安全：delector.core.version 是只吃标准库的叶模块（实测不拉 spacy /
    # fastapi / webview 等重依赖），不会给构建脚本引入副作用，故不采用正则读源码的绕行写法。
    from delector.core.version import APP_VERSION

    raw = tag_ref_name() or f"v{APP_VERSION}"
    # 防御性净化 + 断言：不管版本来自 CI 还是 fallback，都绝不产出含路径分隔符的目录名。
    version = sanitize_version(raw)
    assert_no_path_separator(version)
    return version


def current_commit_short_sha(repo_dir: str) -> str:
    """取当前 HEAD 的短 sha；非 git 环境 / 未装 git / 命令失败一律回落 'unknown'，绝不抛。

    为什么必须回落而非硬失败：没有 git 元数据的源码包（如 CI 下载的 zip）也要能构建，
    sha 取不到只是指纹不完整，不该让整个打包失败。
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip() or "unknown"


def build_fingerprint(version: str, entry: str, commit: str, built_at: str) -> Dict[str, str]:
    """构造机器可读指纹的键值（纯函数，便于守卫直接比对内容）。"""
    return {
        "commit": commit,
        "built_at": built_at,
        "app_version": version,
        "entry": entry,
    }


def write_build_fingerprint(release_dir: str, version: str, entry: str, commit: str, built_at: str) -> str:
    """把指纹写到产物根 `.build-info.json`，返回其绝对路径。"""
    path = os.path.join(release_dir, BUILD_INFO_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_fingerprint(version, entry, commit, built_at), f, ensure_ascii=False, indent=2)
    return path


def readme_fingerprint_line(version: str, commit: str, built_at: str) -> str:
    """README 顶部**一行**人读指纹（版本 + 短 sha + 构建时间）。"""
    return f"构建指纹：{version} · commit {commit} · 构建于 {built_at}"


def release_readme(version: str, commit: str = "unknown", built_at: str = "") -> str:
    """产物内《说明_README.txt》正文（入口的**单一文案真相**）。

    为什么抽成纯函数：入口从"起服务 + 开默认浏览器"改为"打开桌面窗口"后，文案若不同步，用户会照着
    README 找一个已不存在的启动方式 —— 属"文档漂移"类静默失败。抽出来后守卫测试可直接断言文本
    （tests/test_server.py::test_windows_portable_readme_matches_desktop_entry）。

    顶部那行是人读构建指纹（见 readme_fingerprint_line）：用户靠它分辨自己双击的是哪个构建。
    """
    return f"""{readme_fingerprint_line(version, commit, built_at)}

# DeLector — 德语学术精读与备考工作台 ({version} 绿色便携版)

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
    version = resolve_version()
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
        # 子计划 2A：预置文章 spaCy 口径 processed_json 数据文件（见 PRESET_PROCESSED_DATA_REL
        # 的说明）。src 取仓库内相对路径，dest 钉在同一相对路径 ⇒ 运行时按包相对定位能命中。
        f"--add-data={os.path.join(root_dir, PRESET_PROCESSED_DATA_REL)}"
        f"{os.pathsep}{os.path.dirname(PRESET_PROCESSED_DATA_REL)}",
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

    # 4. 验包：产物必须含 WebView2 运行时 DLL（缺 ⇒ 解压后白屏），且不得夹带 .env（防 Key 外泄）。硬失败，非警告。
    assert_webview2_payload(release_dir)
    assert_no_env_in_payload(release_dir)

    # 5. 写机器可读构建指纹 + 人读文案（文案与入口同源：见 release_readme 的单一真相说明）
    commit = current_commit_short_sha(root_dir)
    built_at = datetime.now().isoformat(timespec="seconds")
    write_build_fingerprint(release_dir, version, DEFAULT_ENTRY, commit, built_at)
    with open(os.path.join(release_dir, "说明_README.txt"), "w", encoding="utf-8") as f:
        f.write(release_readme(version, commit, built_at))

    print("\n" + "=" * 60)
    print("[SUCCESS] 绿色便携版打包成功！")
    print(f"发布包目录: {release_dir}")
    print(f"可执行程序: {os.path.join(release_dir, 'DeLector.exe')}")
    print("=" * 60)


if __name__ == "__main__":
    build_windows()
