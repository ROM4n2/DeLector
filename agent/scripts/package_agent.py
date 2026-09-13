#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeLector Agent 绿色便携包打包脚本（Phase 2b T3）。

把 Go 单二进制与 Python venv 组装为自包含分发包 delector-agent/：

    delector-agent/
      ├── delector(.exe)   # go build -trimpath -ldflags "-s -w -X main.version=..."
      ├── python/          # venv：requirements.txt 依赖 + de_core_news_sm 模型
      ├── delector-src/    # delector/ 包 + static/ + start.py（PYTHONPATH 源根）
      └── README.txt       # 启动说明（端口 8001 / DEEPSEEK_API_KEY 仅环境变量）

压缩为 DeLector-Agent-<ver>-<os>-<arch>.zip（windows）/ .tar.gz（unix）。
幂等：重跑清旧产物目录与压缩包。

用法:
    python agent/scripts/package_agent.py [--smoke] [--no-zip]
                                          [--version X.Y.Z] [--skip-venv]

设计约束（Global Constraints）:
    - 绝不内嵌任何 API key 或模型权重；spaCy 模型随 venv 安装（公共资源）。
    - 产制品自包含：delector run 自动使用包内 venv 的 python，不依赖系统 python。
    - 不触碰 package_windows.py / build-release.yml（本脚本独立新增）。

冒烟（--smoke）：起 delector(.exe) run → 轮询 GET /api/tools/ 断言 200 →
Ctrl+C 优雅退出 → 校验进程用的是包内 venv python 且无孤儿。
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile

# stdout/stderr 强制 utf-8，避免 Windows 控制台乱码导致打包日志不可读。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))  # .../agent/scripts
AGENT_DIR = os.path.dirname(SCRIPT_DIR)  # .../agent
REPO_ROOT = os.path.dirname(AGENT_DIR)  # 仓库根
DIST_DIR = os.path.join(REPO_ROOT, "dist", "agent")  # 产物/压缩包暂存
MAIN_GO = os.path.join(AGENT_DIR, "cmd", "delector", "main.go")


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd, cwd=None, env=None, check=True):
    """执行子命令，实时透传输出；失败按 check 退出。"""
    log("+ " + " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=sys.stdout, stderr=sys.stderr)
    if check and r.returncode != 0:
        sys.exit("[Error] 命令失败 (exit=%d): %s" % (r.returncode, " ".join(str(c) for c in cmd)))
    return r


def detect_platform():
    goos = {"win32": "windows", "linux": "linux", "darwin": "darwin"}.get(sys.platform, "windows")
    m = platform.machine().lower()
    goarch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(m, "amd64")
    return goos, goarch


def get_version(override):
    if override:
        return override
    # 解析 main.go 的版本声明（与 ldflags -X main.version 同源）。
    # 兼容多种声明风格（任一命中字符串字面量即取用）：
    #   const version = "x.y.z"
    #   const defaultVersion = "x.y.z"
    #   var version = defaultVersion   （无字面量，跳过并继续，由 defaultVersion 行兜底）
    # 仅当声明行含字符串字面量 "x.y.z" 时取用，避免误命中标识符引用。
    try:
        with open(MAIN_GO, encoding="utf-8") as f:
            for line in f.read().splitlines():
                s = line.strip()
                if not (
                    s.startswith("var version") or s.startswith("const version") or s.startswith("const defaultVersion")
                ):
                    continue
                m = re.search(r'"([^"]*)"', s)
                if m:
                    return m.group(1)
    except Exception as e:  # noqa: BLE001
        log("[Warn] 解析 version 失败: %s" % e)
    return "0.1.0"


def find_go():
    for cand in ("go", "go.exe"):
        p = shutil.which(cand)
        if p:
            return p
    sys.exit("[Error] 找不到 go 可执行文件，请先安装 Go 1.26+ 并加入 PATH")


def build_binary(pkg_dir, goos, goarch, version):
    bin_name = "delector.exe" if goos == "windows" else "delector"
    bin_path = os.path.join(pkg_dir, bin_name)
    env = os.environ.copy()
    env["GOOS"] = goos
    env["GOARCH"] = goarch
    env["CGO_ENABLED"] = "0"
    ldflags = "-s -w -X main.version=%s" % version
    run(
        [find_go(), "build", "-trimpath", "-ldflags", ldflags, "-o", bin_path, "./cmd/delector"], cwd=AGENT_DIR, env=env
    )
    if not os.path.exists(bin_path):
        sys.exit("[Error] 构建产物缺失: %s" % bin_path)
    log("[build] 二进制: %s (%d bytes)" % (bin_path, os.path.getsize(bin_path)))
    return bin_path


def create_venv(pkg_dir, goos, skip_venv):
    venv_dir = os.path.join(pkg_dir, "python")
    if skip_venv and os.path.isdir(venv_dir):
        log("[venv] 跳过创建（--skip-venv，复用已有 %s）" % venv_dir)
    else:
        if os.path.isdir(venv_dir):
            shutil.rmtree(venv_dir)
        run([sys.executable, "-m", "venv", venv_dir])
    # 标准 venv 布局：Windows 解释器在 Scripts/，unix 在 bin/。
    venv_py = (
        os.path.join(venv_dir, "Scripts", "python.exe")
        if goos == "windows"
        else os.path.join(venv_dir, "bin", "python")
    )
    if not os.path.exists(venv_py):
        sys.exit("[Error] venv python 缺失: %s" % venv_py)
    # 升级打包器，再装运行时依赖 + 德语小模型（sm，md 优先但首启动太慢）。
    run([venv_py, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([venv_py, "-m", "pip", "install", "-r", os.path.join(REPO_ROOT, "requirements.txt")])
    run([venv_py, "-m", "spacy", "download", "de_core_news_sm"])
    return venv_dir, venv_py


def _copytree(src, dst, ignore):
    if not os.path.exists(src):
        sys.exit("[Error] 拷贝源缺失: %s" % src)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def copy_src(pkg_dir):
    src_dir = os.path.join(pkg_dir, "delector-src")
    if os.path.isdir(src_dir):
        shutil.rmtree(src_dir)
    os.makedirs(src_dir, exist_ok=True)
    # 排除字节码缓存与版本控制目录，保持源根干净、体积可控。
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git", ".github")
    _copytree(os.path.join(REPO_ROOT, "delector"), os.path.join(src_dir, "delector"), ignore)
    _copytree(os.path.join(REPO_ROOT, "static"), os.path.join(src_dir, "static"), ignore)
    shutil.copy2(os.path.join(REPO_ROOT, "start.py"), os.path.join(src_dir, "start.py"))
    log("[src] 源根: %s（delector/ + static/ + start.py）" % src_dir)
    return src_dir


def write_readme(pkg_dir, version, goos):
    bin_name = "delector.exe" if goos == "windows" else "delector"
    content = (
        "DeLector Agent 绿色便携包（%s）\n"
        "================================\n\n"
        "== 启动 ==\n"
        "直接运行可执行程序，常驻至 Ctrl+C：\n"
        "    ./%s run\n"
        "客户端/浏览器访问：http://127.0.0.1:8001\n\n"
        "== 端口 ==\n"
        "默认 8001。如需改端口：\n"
        "    ./%s run --port 9001\n\n"
        "== 数据目录 ==\n"
        "默认写到本包目录（delector.db 与缓存），不触碰用户库。\n"
        "可用 --data-dir 指定：\n"
        "    ./%s run --data-dir /path/to/data\n\n"
        "== API Key（凭证纪律）==\n"
        "DEEPSEEK_API_KEY 仅从环境变量读取，产物绝不内嵌任何 key 或模型权重。\n"
        "启动前在终端设置：\n"
        "    set DEEPSEEK_API_KEY=sk-xxx      （Windows cmd）\n"
        "    export DEEPSEEK_API_KEY=sk-xxx   （bash/zsh）\n\n"
        "== 自包含说明 ==\n"
        "python/ 是随包分发的 venv（含 requirements.txt 依赖 + de_core_news_sm\n"
        "模型）；delector run 自动使用包内 venv 的 python，不依赖系统 python。\n"
        "delector-src/ 是 Python 源根（delector 包 + static + start.py），\n"
        "经 PYTHONPATH 注入，使 uvicorn 可 import delector.server:app。\n"
    ) % (version, bin_name, bin_name, bin_name)
    with open(os.path.join(pkg_dir, "README.txt"), "w", encoding="utf-8") as f:
        f.write(content)
    log("[readme] 已写 README.txt")


def _should_skip(entry_name):
    return entry_name == "__pycache__" or entry_name.endswith(".pyc")


def package_archive(pkg_dir, version, goos, goarch, no_zip):
    name = "DeLector-Agent-%s-%s-%s" % (version, goos, goarch)
    if no_zip:
        log("[pkg] --no-zip：跳过压缩，产物目录 %s" % pkg_dir)
        return None
    if goos == "windows":
        arc_path = os.path.join(DIST_DIR, name + ".zip")
        if os.path.exists(arc_path):
            os.remove(arc_path)
        with zipfile.ZipFile(arc_path, "w", zipfile.ZIP_DEFLATED) as z:
            for root, dirs, files in os.walk(pkg_dir):
                dirs[:] = [d for d in dirs if not _should_skip(d)]
                for fn in files:
                    if fn.endswith(".pyc"):
                        continue
                    fp = os.path.join(root, fn)
                    z.write(fp, os.path.relpath(fp, pkg_dir))
    else:
        arc_path = os.path.join(DIST_DIR, name + ".tar.gz")
        if os.path.exists(arc_path):
            os.remove(arc_path)

        def _filter(ti):
            if ti.name.endswith(".pyc") or os.path.basename(ti.name) == "__pycache__":
                return None
            return ti

        with tarfile.open(arc_path, "w:gz") as t:
            t.add(pkg_dir, arcname="delector-agent", filter=_filter)
    size = os.path.getsize(arc_path)
    log("[pkg] 压缩包: %s (%d bytes ≈ %.1f MB)" % (arc_path, size, size / 1024.0 / 1024.0))
    return arc_path


# ----------------------------- 冒烟验证 -----------------------------


def _http_ok(url, timeout=3.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def _venv_python_path(pkg_dir, goos):
    venv_dir = os.path.join(pkg_dir, "python")
    if goos == "windows":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def _terminate(proc, goos):
    """跨平台优雅终止：windows 发 CTRL_BREAK_EVENT（→ Go os.Interrupt），
    unix 发 SIGTERM；均被 delector run 的 NotifyContext 捕获触发优雅退出。"""
    try:
        if goos == "windows":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except Exception as e:  # noqa: BLE001
        log("[smoke] 发送终止信号失败: %s" % e)


def _orphan_python(pkg_dir, goos):
    """返回仍运行在包内 venv 下的 python 进程 exe 路径列表（孤儿判定）。"""
    venv_prefix = os.path.join(pkg_dir, "python").replace("\\", "/").lower()
    found = []
    if goos == "windows":
        try:
            ps = "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.ExecutablePath }"
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=15
            ).stdout
            for line in out.splitlines():
                p = line.strip().replace("\\", "/").lower()
                if p.startswith(venv_prefix) and p.endswith("python.exe"):
                    found.append(p)
        except Exception as e:  # noqa: BLE001
            log("[smoke] 孤儿进程探测失败（powershell）: %s" % e)
    else:
        try:
            out = subprocess.run(["pgrep", "-f", venv_prefix], capture_output=True, text=True, timeout=15).stdout
            if out.strip():
                found.append(out.strip())
        except Exception:  # noqa: BLE001
            pass
    return found


def smoke(pkg_dir, goos, port=8001):
    bin_name = "delector.exe" if goos == "windows" else "delector"
    bin_path = os.path.join(pkg_dir, bin_name)
    url = "http://127.0.0.1:%d/api/tools/" % port
    log("[smoke] 启动 %s run --port %d ..." % (bin_path, port))

    kwargs = {}
    if goos == "windows":
        # 新进程组，使 CTRL_BREAK_EVENT 仅送达该组（Go 二进制控制台处理器）。
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # 显式 utf-8 + replace：uvicorn 日志可能含非本机 locale 字节，避免读取
    # 线程因 gbk 等默认编码解码失败而崩（曾导致冒烟 reader 线程异常）。
    proc = subprocess.Popen(
        [bin_path, "run", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **kwargs,
    )

    captured = []

    def _reader():
        for line in proc.stdout:
            line = line.rstrip("\n")
            captured.append(line)
            log("   | " + line)

    thr = threading.Thread(target=_reader, daemon=True)
    thr.start()

    ok = False
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        if _http_ok(url):
            ok = True
            break
        time.sleep(0.5)

    if not ok:
        _terminate(proc, goos)
        proc.wait(timeout=10)
        sys.exit("[smoke] 超时：%s 未返回 200（诊断见上）" % url)

    log("[smoke] GET %s -> 200 OK" % url)

    # 优雅退出（Ctrl+C 等价）。
    _terminate(proc, goos)
    try:
        proc.wait(timeout=10)
        log("[smoke] 进程已优雅退出 rc=%s" % proc.returncode)
    except subprocess.TimeoutExpired:
        log("[smoke] 优雅退出超时，强制结束")
        proc.kill()
        proc.wait(timeout=5)

    venv_py = _venv_python_path(pkg_dir, goos).replace("\\", "/")
    used = any(venv_py in (ln or "").replace("\\", "/") for ln in captured)
    if not used:
        # 进程树回退校验：确有 venv python 在跑（诊断日志缺失时）。
        orphans_running = _orphan_python(pkg_dir, goos)
        used = bool(orphans_running)
    if used:
        log("[smoke] 确认使用包内 venv python: %s" % venv_py)
    else:
        sys.exit("[smoke] 未能确认使用包内 venv python（期望 %s）" % venv_py)

    # 退出后不应残留 venv python 孤儿进程。
    orphans = _orphan_python(pkg_dir, goos)
    if orphans:
        sys.exit("[smoke] 检测到 venv python 孤儿进程（Ctrl+C 未干净退出）: %s" % orphans)
    log("[smoke] 无孤儿进程 ✓")
    log("[smoke] PASS")


# ----------------------------- 主流程 -----------------------------


def main():
    ap = argparse.ArgumentParser(description="DeLector Agent 绿色便携包打包")
    ap.add_argument("--smoke", action="store_true", help="打包后启动 delector run 并断言 /api/tools/ 200")
    ap.add_argument("--no-zip", action="store_true", help="不压缩，仅产出 delector-agent/ 目录")
    ap.add_argument("--version", default=None, help="覆盖版本号（默认解析 main.go const version）")
    ap.add_argument("--skip-venv", action="store_true", help="复用已有 python/ venv，跳过重建（加速迭代）")
    args = ap.parse_args()

    goos, goarch = detect_platform()
    version = get_version(args.version)
    log("=" * 60)
    log("  DeLector Agent 打包  v%s  (%s/%s)" % (version, goos, goarch))
    log("=" * 60)

    pkg_dir = os.path.join(DIST_DIR, "delector-agent")
    # 幂等：清旧产物目录与压缩包。
    if os.path.isdir(pkg_dir):
        shutil.rmtree(pkg_dir)
    os.makedirs(pkg_dir, exist_ok=True)
    for fn in os.listdir(DIST_DIR):
        if fn.startswith("DeLector-Agent-") and (fn.endswith(".zip") or fn.endswith(".tar.gz")):
            os.remove(os.path.join(DIST_DIR, fn))

    # 1) Go 二进制
    build_binary(pkg_dir, goos, goarch, version)
    # 2) Python venv（依赖 + 模型）
    create_venv(pkg_dir, goos, args.skip_venv)
    # 3) Python 源根
    copy_src(pkg_dir)
    # 4) README
    write_readme(pkg_dir, version, goos)
    # 5) 压缩
    arc = package_archive(pkg_dir, version, goos, goarch, args.no_zip)

    # 产物体积统计
    total = 0
    for root, _dirs, files in os.walk(pkg_dir):
        for fn in files:
            total += os.path.getsize(os.path.join(root, fn))
    log("-" * 60)
    log("产物目录: %s" % pkg_dir)
    log("产物体积: %.1f MB（含 venv + de_core_news_sm 模型）" % (total / 1024.0 / 1024.0))
    if arc:
        log("压缩包:   %s (%.1f MB)" % (arc, os.path.getsize(arc) / 1024.0 / 1024.0))
    log("-" * 60)

    if args.smoke:
        smoke(pkg_dir, goos)
        log("=" * 60)
        log("全流程完成 + 冒烟通过 ✓")
        log("=" * 60)
    else:
        log("=" * 60)
        log("打包完成 ✓（加 --smoke 可本地起服务冒烟）")
        log("=" * 60)


if __name__ == "__main__":
    main()
