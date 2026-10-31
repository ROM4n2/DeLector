# -*- coding: utf-8 -*-
"""Go 伴学 Agent 子进程生命周期守护器 (GoAgentSupervisor).

职责：
1. 探测本机预编译二进制 (agent/delector.exe) 或系统 PATH 上的 go 命令；
2. 自动以守护进程方式拉起 Go 伴学 Agent (默认 8002 端口)；
3. 有界轮询 /api/companion/health 端点判定就绪；
4. 退出时执行优雅终止 (terminate + wait + kill 降级)，彻底杜绝孤儿进程与端口霸占；
5. 在未装 Go 环境或 Android 平台上安全返回 False 并降级为 Python 内核，绝不阻断主服务。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import httpx

_logger = logging.getLogger("delector.agent_supervisor")

DEFAULT_GO_AGENT_PORT: int = 8002
DEFAULT_STARTUP_DEADLINE_S: float = 5.0
DEFAULT_SHUTDOWN_GRACE_S: float = 5.0
HEALTH_POLL_INTERVAL_S: float = 0.2


class GoAgentSupervisor:
    """管理 Go 伴学 Agent 常驻子进程生命周期."""

    def __init__(
        self,
        port: int = DEFAULT_GO_AGENT_PORT,
        root_dir: Optional[Path] = None,
        python_url: str = "http://127.0.0.1:8001",
    ) -> None:
        self.port = port
        self.root_dir = root_dir or Path(__file__).resolve().parents[2]
        self.agent_dir = self.root_dir / "agent"
        self.python_url = python_url
        self.proc: Optional[subprocess.Popen[Any]] = None

    def find_command(self) -> Tuple[Optional[List[str]], Path]:
        """探测可用的 Go 伴学 Agent 启动命令与工作目录."""
        # 1. 优先探测是否已构建独立二进制 (delector.exe 或 delector)
        candidate_names = ["delector.exe", "delector"] if os.name == "nt" else ["delector", "delector.exe"]
        for name in candidate_names:
            bin_path = self.agent_dir / name
            if bin_path.is_file() and os.access(bin_path, os.X_OK):
                return [str(bin_path), "agent", "--port", str(self.port)], self.agent_dir

        # 2. 次优探测系统 PATH 是否安装了 go CLI
        go_bin = shutil.which("go")
        if go_bin and (self.agent_dir / "go.mod").exists():
            return [
                go_bin,
                "run",
                "./cmd/delector",
                "agent",
                "--port",
                str(self.port),
            ], self.agent_dir

        # 3. 未找到 Go 运行环境
        return None, self.agent_dir

    def is_healthy(self, timeout_s: float = 1.0) -> bool:
        """探测 8002 伴学健康探针是否就绪."""
        try:
            url = f"http://127.0.0.1:{self.port}/api/companion/health"
            resp = httpx.get(url, timeout=timeout_s)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return bool(data.get("status") == "ok")
        except Exception:
            pass
        return False

    def is_running(self) -> bool:
        """检查子进程是否处于运行状态."""
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def start(self, deadline_s: float = DEFAULT_STARTUP_DEADLINE_S) -> bool:
        """拉起 Go 伴学 Agent 子进程并有界等待其健康就绪."""
        # 如果已经有健康的实例在跑，直接复用
        if self.is_healthy():
            _logger.info("Go 伴学 Agent 已在端口 %d 就绪，直接复用", self.port)
            return True

        cmd, cwd = self.find_command()
        if not cmd:
            _logger.info("未检测到 Go 运行时或预编译二进制，伴学功能平滑回退至 Python 内核")
            return False

        try:
            _logger.info("正在拉起 Go 伴学子进程: %s (cwd=%s)", " ".join(cmd), cwd)
            # 子进程标准流丢弃或由系统管理，避免缓冲区死锁
            self.proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            _logger.warning("拉起 Go 伴学 Agent 进程异常: %s", exc)
            self.proc = None
            return False

        start_time = time.monotonic()
        while time.monotonic() - start_time < deadline_s:
            if not self.is_running():
                _logger.warning("Go 伴学 Agent 进程已意外退出 (exit_code=%s)", self.proc.poll() if self.proc else None)
                self.stop()
                return False

            if self.is_healthy(timeout_s=0.5):
                _logger.info("Go 伴学 Agent 成功拉起并在端口 %d 就绪", self.port)
                return True

            time.sleep(HEALTH_POLL_INTERVAL_S)

        _logger.warning("Go 伴学 Agent 启动超时 (%.1fs)，正在终止子进程", deadline_s)
        self.stop()
        return False

    def stop(self, grace_s: float = DEFAULT_SHUTDOWN_GRACE_S) -> None:
        """优雅终止 Go 伴学 Agent 子进程并彻底收尸."""
        if self.proc is None:
            return

        proc = self.proc
        self.proc = None

        if proc.poll() is not None:
            return

        try:
            _logger.info("正在发送终止信号给 Go 伴学 Agent (PID=%s)...", getattr(proc, "pid", "unknown"))
            proc.terminate()
            proc.wait(timeout=grace_s)
            _logger.info("Go 伴学 Agent 已干净退出")
        except subprocess.TimeoutExpired:
            _logger.warning("Go 伴学 Agent 未在 %.1fs 宽限期内退出，强制强杀 (kill)...", grace_s)
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
        except Exception as exc:
            _logger.warning("收尸 Go 伴学 Agent 异常: %s", exc)
