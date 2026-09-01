#!/usr/bin/env python3
"""
DeLector - Windows Portable Packager
Builds a standalone, zero-dependency Windows portable distribution.
"""
import os
import sys
import shutil
import subprocess

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

def build_windows():
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
        sys.executable, "-m", "PyInstaller",
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
        "--hidden-import=core_dict",
        "--hidden-import=core_dict_ext",
        "--hidden-import=prep_dict",
        "--hidden-import=a1_dict",
        "--hidden-import=a1_writing_dict",
        "--hidden-import=a1_hoeren_dict",
        "--hidden-import=a1_lesen_dict",
        "--hidden-import=corpus_dict",
        "--hidden-import=routes_a1",
        "--hidden-import=routes_a1_hoeren",
        "--hidden-import=routes_a1_lesen",
        "--hidden-import=routes_corpus",
        "--hidden-import=routes_sync",
        "--hidden-import=de_core_news_sm",
        "--hidden-import=spacy.lang.de",
        "--hidden-import=genanki",
        "--hidden-import=edge_tts",
        "--hidden-import=httpx",
        "--collect-all=de_core_news_sm",
        "--collect-all=spacy",
        os.path.join(root_dir, "start.py")
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

    # 4. Copy helper files
    readme_content = f"""# DeLector — 德语学术精读与备考工作台 ({version} 绿色便携版)

## 🚀 启动方式
直接双击运行 `DeLector.exe` 即可自动启动服务并在默认浏览器中打开工作台！

## ⚙️ API 配置 (可选)
软件内置 0ms 德语核心词库、形态学三态表、复合词拆解、五场域拓扑与从句树分析，全部 100% 离线运行。
如需使用 DeepSeek 深度 AI 考点剖析，在页面右上角点击「⚙️ 设置」填入 API Key 即可。

## 📱 手机 / 平板局域网伴读
保持电脑与手机在同一 Wi-Fi 下，手机浏览器访问控制台显示的局域网 IP（例如 `http://192.168.x.x:8000`）即可同步阅读！
"""
    with open(os.path.join(release_dir, "说明_README.txt"), "w", encoding="utf-8") as f:
        f.write(readme_content)

    print("\n" + "=" * 60)
    print("[SUCCESS] 绿色便携版打包成功！")
    print(f"发布包目录: {release_dir}")
    print(f"可执行程序: {os.path.join(release_dir, 'DeLector.exe')}")
    print("=" * 60)

if __name__ == "__main__":
    build_windows()
