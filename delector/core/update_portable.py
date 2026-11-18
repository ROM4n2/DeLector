# -*- coding: utf-8 -*-
"""Windows 便携版的目录交换（解压 + 生成 helper 脚本）。

硬约束：运行中的 ``DeLector.exe`` 与 ``_internal`` 下的 DLL 被文件锁占用，不能原地覆盖。
做法是把新版本解压到临时目录，由 ``%TEMP%`` 里的 PowerShell helper 等进程退出后：
备份旧目录 → 复制新目录 → 启动新版 → 删备份。任一步失败则把备份换回去。

helper 必须是**文本脚本**而不是应用内的函数：应用退出后没人执行 Python。
"""

import shutil
import zipfile
from pathlib import Path
from typing import List

__all__ = [
    "build_apply_script",
    "install_root",
    "is_writable_root",
    "powershell_command",
    "prepare_payload",
]


def install_root(executable: Path) -> Path:
    """便携版的安装根目录 = exe 所在目录。"""
    return executable.resolve().parent


def is_writable_root(root: Path) -> bool:
    """探测目标目录可写；只读安装（如 Program Files）不允许冒险替换。"""
    probe = root / ".delector-write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def prepare_payload(archive: Path, staging: Path) -> Path:
    """把 zip 解压到 staging，返回包含 ``DeLector.exe`` 的目录。

    zip 条目做路径穿越检查：不含 ``..`` 逃逸，也不写绝对路径。
    """
    staging = staging.resolve()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (staging / member.filename).resolve()
            if target != staging and staging not in target.parents:
                raise ValueError(f"压缩包条目逃逸目标目录: {member.filename!r}")
        handle.extractall(staging)

    executable = next(iter(staging.rglob("DeLector.exe")), None)
    if executable is None:
        raise ValueError("压缩包内缺少 DeLector.exe")
    return executable.parent


def _ps(value: str) -> str:
    """PowerShell 单引号字面量：内部的 ``'`` 双写，防止路径注入。"""
    return "'" + value.replace("'", "''") + "'"


def build_apply_script(
    *,
    pid: int,
    source_dir: Path,
    target_dir: Path,
    restart_exe: Path,
    backup_dir: Path,
    log_path: Path,
) -> str:
    """生成等待退出 → 备份 → 复制 → 重启 → 清理的 PowerShell 脚本。"""
    return "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            f"$target = {_ps(str(target_dir))}",
            f"$source = {_ps(str(source_dir))}",
            f"$backup = {_ps(str(backup_dir))}",
            f"$restart = {_ps(str(restart_exe))}",
            f"$log = {_ps(str(log_path))}",
            "try { Wait-Process -Id " + str(int(pid)) + " -Timeout 120 -ErrorAction SilentlyContinue } catch { }",
            "Start-Sleep -Milliseconds 800",
            "if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }",
            "$moved = $false",
            "try {",
            "  if (Test-Path -LiteralPath $target) {",
            "    Move-Item -LiteralPath $target -Destination $backup -Force",
            "    $moved = $true",
            "  }",
            "  New-Item -ItemType Directory -Path $target -Force | Out-Null",
            "  Copy-Item -Path (Join-Path $source '*') -Destination $target -Recurse -Force",
            "  Start-Process -FilePath $restart -WorkingDirectory $target",
            "} catch {",
            "  if ($moved -and (Test-Path -LiteralPath $backup)) {",
            "    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }",
            "    Move-Item -LiteralPath $backup -Destination $target -Force",
            "  }",
            "  Add-Content -LiteralPath $log -Value $_.Exception.Message",
            "  exit 1",
            "}",
            "if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }",
            "Remove-Item -LiteralPath $source -Recurse -Force -ErrorAction SilentlyContinue",
            "",
        ]
    )


def powershell_command(script_path: Path) -> List[str]:
    """以无配置、无交互方式运行 helper；``-File`` 后只跟一个受控路径。"""
    return [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
