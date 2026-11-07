# -*- coding: utf-8 -*-
"""Go 伴学 Agent 子进程生命周期守护器 (GoAgentSupervisor).

职责：
1. 探测本机预编译二进制 (agent/delector.exe) 或系统 PATH 上的 go 命令；
2. 为 Go 伴学 Agent 选一个**与 Python 主服务互斥**的空闲端口（首选 8002，冲突时 8011–8015）；
3. 有界轮询 /api/companion/health 端点判定就绪（并校验 service 身份，不只看 status）；
4. 退出时执行优雅终止 (terminate + wait + kill 降级)，彻底杜绝孤儿进程与端口霸占；
5. 无法启动时**响亮**降级为 Python 内核：日志写明「桌宠 agent 桥不可用」，绝不假装成功。
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

import httpx

_logger = logging.getLogger("delector.agent_supervisor")

DEFAULT_GO_AGENT_PORT: int = 8002
DEFAULT_PYTHON_PORT: int = 8000
DEFAULT_STARTUP_DEADLINE_S: float = 15.0
DEFAULT_SHUTDOWN_GRACE_S: float = 5.0
HEALTH_POLL_INTERVAL_S: float = 0.2

#: Go 伴学 Agent 的端口候选。8002 是历史默认；一旦与 Python 实际端口冲突或被占用，
#: 顺延到 8011–8015 —— 这段区间 Python 的 `PORT_CANDIDATES` 永不使用，故不会出现
#: 「Go 抢了主服务的端口」。**不得**把 Go 端口也放进 Python 的候选区间。
GO_AGENT_PORT_CANDIDATES: tuple[int, ...] = (8002, 8011, 8012, 8013, 8014, 8015)

#: Go 伴学 Agent `/api/companion/health` 的 service 身份值
#: （`agent/internal/companion/server.go` 的 `service` 字段）。只判 `status == "ok"`
#: 不够：任何实现同路径的服务（例如未来 Python 补了该端点）都会被误认成 Go Agent，
#: 于是「桥断了」被报成「桥正常」。
GO_AGENT_SERVICE_ID: str = "delector-go-companion-agent"

#: 降级时给用户看的那一句（start.py 与日志共用，避免两处措辞漂移）。
DEGRADED_MESSAGE: str = "Go 内核不可用，已降级 Python 内核，桌宠 agent 桥不可用"


def _port_in_use(port: int) -> bool:
    """本机端口是否已被监听（与 `start.is_port_in_use` 同判据）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def pick_agent_port(
    python_port: int,
    probe: Callable[[int], bool] = _port_in_use,
) -> Optional[int]:
    """为 Go 伴学 Agent 选一个**与 Python 主服务互斥**的空闲端口；无可用返回 None。

    跳过 `python_port` 是硬约束（不是优化）：两者同端口时，Windows 实测允许
    `127.0.0.1:8002`（Go）与 `0.0.0.0:8002`（Python）**同时监听**，而 127.0.0.1 的
    连接会落到 Go —— Python 的页面与 `/api/health` 直接 404，启动日志却还写着
    「Go Agent 已自动托管启动」。这比「Go 起不来」更难归因，故必须从分配阶段排除。
    """
    for candidate in GO_AGENT_PORT_CANDIDATES:
        if candidate == python_port:
            continue
        if not probe(candidate):
            return candidate
    return None


class GoAgentSupervisor:
    """管理 Go 伴学 Agent 常驻子进程生命周期."""

    def __init__(
        self,
        port: Optional[int] = None,
        root_dir: Optional[Path] = None,
        python_url: Optional[str] = None,
        python_port: int = DEFAULT_PYTHON_PORT,
    ) -> None:
        self.python_port = python_port
        # 不传 port ⇒ 走**互斥分配**，与 Python 实际端口比对后再取空闲值。
        # 显式传入仍尊重（测试 / 运维手工指定），但 start() 会拒绝与 Python 端口相同的值 ——
        # 绝不在主服务的监听点上再放一个 Go 监听者。
        picked = port if port is not None else pick_agent_port(python_port)
        # 0 是「没有可用端口」的哨兵：find_command / is_healthy 只在 start() 校验通过后调用。
        self.port: int = picked if picked is not None else 0
        self.root_dir = root_dir or Path(__file__).resolve().parents[2]
        self.agent_dir = self.root_dir / "agent"
        self.python_url = python_url or f"http://127.0.0.1:{python_port}"
        self.proc: Optional[subprocess.Popen[Any]] = None
        # 最近一次失败原因（start() 失败时由 start.py 写进日志 / 状态）。
        self.last_error: str = ""
        # 子进程 stdout+stderr 落到临时文件：既避免缓冲区死锁，又能在启动失败时把
        # Go 侧的真实报错（如 bind: Only one usage of each socket address）读回来 ——
        # 旧实现丢进 DEVNULL，端口占用只能看到一个没有原因的「启动超时」。
        self._child_output: Optional[Any] = None

    def find_command(self) -> Tuple[Optional[List[str]], Path]:
        """探测可用的 Go 伴学 Agent 启动命令与工作目录."""
        # 1. 优先探测是否已构建独立二进制 (delector.exe 或 delector)
        candidate_names = ["delector.exe", "delector"] if os.name == "nt" else ["delector", "delector.exe"]
        for name in candidate_names:
            bin_path = self.agent_dir / name
            if bin_path.is_file() and os.access(bin_path, os.X_OK):
                return [
                    str(bin_path),
                    "agent",
                    "--port",
                    str(self.port),
                    "--python-url",
                    self.python_url,
                ], self.agent_dir

        # 2. 次优探测系统 PATH 是否安装了 go CLI
        go_bin = shutil.which("go")
        if go_bin and (self.agent_dir / "go.mod").exists():
            # 自动预编译二进制，规避 Windows 平台每次 go run 冷编译造成的启动超时
            target_bin_name = "delector.exe" if os.name == "nt" else "delector"
            target_bin = self.agent_dir / target_bin_name
            try:
                build_proc = subprocess.run(
                    [go_bin, "build", "-o", str(target_bin), "./cmd/delector"],
                    cwd=str(self.agent_dir),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=15.0,
                )
                if build_proc.returncode == 0 and target_bin.is_file() and os.access(target_bin, os.X_OK):
                    return [
                        str(target_bin),
                        "agent",
                        "--port",
                        str(self.port),
                        "--python-url",
                        self.python_url,
                    ], self.agent_dir
            except Exception:  # silent-ok: 预编译二进制构建失败时透明回退到 go run 源码执行
                pass

            return [
                go_bin,
                "run",
                "./cmd/delector",
                "agent",
                "--port",
                str(self.port),
                "--python-url",
                self.python_url,
            ], self.agent_dir

        # 3. 未找到 Go 运行环境
        return None, self.agent_dir

    def is_healthy(self, timeout_s: float = 1.0) -> bool:
        """探测伴学健康探针是否就绪（**同时校验 service 身份**）."""
        if self.port <= 0:
            return False
        try:
            url = f"http://127.0.0.1:{self.port}/api/companion/health"
            resp = httpx.get(url, timeout=timeout_s)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    # 只有 Go 伴学 Agent 才带这个 service 值。只认 status=ok 会把
                    # 「别的服务恰好实现了同路径」误判成就绪，进而静默停在这个端口上。
                    return bool(
                        data.get("status") == "ok" and data.get("service") == GO_AGENT_SERVICE_ID
                    )
        except Exception:  # silent-ok: 就绪轮询探测：端口未监听或连接被拒属预期非就绪态，返回 False
            pass
        return False

    def is_running(self) -> bool:
        """检查子进程是否处于运行状态."""
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def start(self, deadline_s: float = DEFAULT_STARTUP_DEADLINE_S) -> bool:
        """拉起 Go 伴学 Agent 子进程并有界等待其健康就绪."""
        self.last_error = ""
        if self.port <= 0:
            self.last_error = (
                f"没有可用的伴学端口（候选 {GO_AGENT_PORT_CANDIDATES} 均被占用，"
                f"或与 Python 端口 {self.python_port} 冲突）"
            )
            _logger.error("Go 内核不可用：%s；%s", self.last_error, DEGRADED_MESSAGE)
            return False
        if self.port == self.python_port:
            # 显式 port 撞上 Python：拒绝启动。Windows 允许两者同时 bind（见 pick_agent_port），
            # 后果是 Go 静默抢走主服务的全部流量，必须在这里硬拦住。
            self.last_error = f"Go 端口 {self.port} 与 Python 主服务端口相同"
            _logger.error("Go 内核不可用：%s；%s", self.last_error, DEGRADED_MESSAGE)
            return False

        # 如果已经有健康的实例在跑（且身份确为 Go Agent），直接复用
        if self.is_healthy():
            _logger.info("Go 伴学 Agent 已在端口 %d 就绪，直接复用", self.port)
            return True

        cmd, cwd = self.find_command()
        if not cmd:
            self.last_error = "未检测到 Go 运行时或预编译二进制"
            _logger.error("Go 内核不可用（%s）；%s", self.last_error, DEGRADED_MESSAGE)
            return False

        try:
            env = os.environ.copy()
            # 自动补充读取仓库根与 agent 目录下的 .env，确保凭证与配置能透传至 Go Agent
            for base_dir in [str(self.root_dir), str(self.agent_dir), os.getcwd()]:
                env_file = Path(base_dir) / ".env"
                if env_file.is_file():
                    try:
                        with open(env_file, "r", encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith("#") and "=" in line:
                                    k, v = line.split("=", 1)
                                    k = k.strip()
                                    v = v.strip().strip("'").strip('"')
                                    if k and k not in env:
                                        env[k] = v
                    except Exception:  # silent-ok: .env 文件损坏或不可读时不阻断主配置加载
                        pass

            try:
                from delector.core.db.settings import (
                    get_effective_api_base_url,
                    get_effective_api_key,
                    get_effective_api_model,
                    get_effective_reasoning_effort,
                )

                eff_key = get_effective_api_key()
                if eff_key:
                    env["DEEPSEEK_API_KEY"] = eff_key
                eff_base = get_effective_api_base_url()
                if eff_base:
                    env["API_BASE_URL"] = eff_base
                eff_model = get_effective_api_model()
                if eff_model:
                    env["API_MODEL"] = eff_model
                eff_effort = get_effective_reasoning_effort()
                if eff_effort:
                    env["DELECTOR_REASONING_EFFORT"] = eff_effort
            except Exception as s_err:
                _logger.debug("读取数据库配置同步至 Go 伴学 Agent 失败 (%s)", s_err)

            _logger.info("正在拉起 Go 伴学子进程: %s (cwd=%s)", " ".join(cmd), cwd)
            # 子进程输出落临时文件而非 DEVNULL：不经 PIPE 故无缓冲区死锁风险，同时把
            # Go 侧的真实报错留给失败路径读取（端口占用 / 编译失败都能说清原因）。
            self._child_output = tempfile.TemporaryFile()
            self.proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=self._child_output,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            self.last_error = f"拉起子进程异常: {exc}"
            _logger.error("Go 内核不可用（%s）；%s", self.last_error, DEGRADED_MESSAGE)
            self.proc = None
            self._close_child_output()
            return False

        start_time = time.monotonic()
        while time.monotonic() - start_time < deadline_s:
            if not self.is_running():
                exit_code = self.proc.poll() if self.proc else None
                detail = self._read_child_output()
                self.last_error = f"进程意外退出 (exit_code={exit_code})"
                if detail:
                    self.last_error += f": {detail}"
                _logger.error("Go 内核不可用：%s；%s", self.last_error, DEGRADED_MESSAGE)
                self.stop()
                return False

            if self.is_healthy(timeout_s=0.5):
                _logger.info("Go 伴学 Agent 成功拉起并在端口 %d 就绪", self.port)
                return True

            time.sleep(HEALTH_POLL_INTERVAL_S)

        detail = self._read_child_output()
        self.last_error = f"启动超时 ({deadline_s:.1f}s)"
        if detail:
            self.last_error += f": {detail}"
        _logger.error("Go 内核不可用：%s；%s", self.last_error, DEGRADED_MESSAGE)
        self.stop()
        return False

    def _read_child_output(self, limit: int = 2000) -> str:
        """读回子进程最后一段输出（仅用于失败归因；拿不到就返回空串）。"""
        handle = self._child_output
        if handle is None:
            return ""
        try:
            handle.seek(0)
            raw = handle.read()
            if isinstance(raw, bytes):
                return raw[-limit:].decode("utf-8", errors="replace").strip()
            return str(raw)[-limit:].strip()
        except Exception:
            return ""

    def _close_child_output(self) -> None:
        handle = self._child_output
        self._child_output = None
        if handle is not None:
            try:
                handle.close()
            except Exception:  # silent-ok: 临时文件已在子进程退出时关闭等情形，收尾无需再抛
                pass

    def stop(self, grace_s: float = DEFAULT_SHUTDOWN_GRACE_S) -> None:
        """优雅终止 Go 伴学 Agent 子进程并彻底收尸."""
        proc = self.proc
        self.proc = None

        if proc is not None and proc.poll() is None:
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
                except Exception:  # silent-ok: 强杀后进程可能已消亡或处于僵尸态，收尸完成无需再抛
                    pass
            except Exception as exc:
                _logger.warning("收尸 Go 伴学 Agent 异常: %s", exc)

        self._close_child_output()
