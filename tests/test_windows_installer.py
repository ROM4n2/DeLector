"""Windows 安装器（Inno Setup 6）守卫。

为什么要有这个闸：安装器是**发布面**最后一环，而它身上的要害全是「静默失败」型：

1. **版本号写死在 .iss 里** ⇒ 产物自称一个版本、应用自报另一个版本 —— 与
   v5.16.0 那次「产物命名成 v3.8.0、App 实为 v5.16.0，用户更新提示永远显示落后」同款。
   故版本必须由 CI 以 ``/DAppVersion=`` 传入，单一真相源仍是 ``delector/core/version.py``。
2. **装到 Program Files** ⇒ 要 UAC，与「免管理员、解压即用」的定位相悖。
3. **卸载器删掉 ``%LOCALAPPDATA%\\DeLector``** ⇒ 用户学习记录被清空，不可逆。
   安装目录与数据目录必须分离，且脚本里不得出现 ``[UninstallDelete]``。
4. **未做代码签名**（无经费）⇒ 既不能偷偷配签名工具，也**必须**在发布正文里如实写明
   「未签名、SmartScreen 可能提示未知发布者」，否则用户会以为是恶意程序。

另外钉住「装包**独立成 job**」：主 CI（``build-windows``）不得被 Inno Setup 拖慢，
装包 job 只在真 tag 或手动触发时跑。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ISS_PATH = REPO_ROOT / "installer" / "DeLector.iss"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "build-release.yml"

INSTALLER_JOB = "build-windows-installer"
INSTALLER_ARTIFACT = "DeLector-Windows-Installer"
SETUP_GLOB = "DeLector-*-Windows-x64-Setup.exe"


# ── 判定器（纯函数：便于对变异副本做自证）────────────────────────────────────
def _strip_iss_comments(text: str) -> str:
    """去掉 .iss 的整行注释（分号开头）。

    为什么必须去：脚本头部**故意**写了「免得将来有人加 [UninstallDelete] 时误伤」
    这类说明，若不剥离，注释里的字样会被当成真配置 ⇒ 判据假红。
    """
    return "".join(ln for ln in text.splitlines(True) if not ln.lstrip().startswith(";"))


def _iss_violations(text: str) -> list[str]:
    """返回 .iss 脚本的违规清单（空清单 = 通过）。"""
    text = _strip_iss_comments(text)
    out: list[str] = []
    if "PrivilegesRequired=lowest" not in text:
        out.append("安装器不是 per-user（PrivilegesRequired 未设 lowest ⇒ 会弹 UAC）")
    default_dir = next((ln for ln in text.splitlines() if ln.startswith("DefaultDirName=")), "")
    if "{localappdata}" not in default_dir.lower():
        out.append(f"安装目录不在用户目录下：{default_dir!r}")
    if "[UninstallDelete]" in text:
        out.append("脚本含 [UninstallDelete]：卸载可能删掉安装目录外的东西（含用户数据）")
    if "{#AppVersion}" not in text:
        out.append("版本号未走 {#AppVersion} 注入（写死 ⇒ 产物版本与应用自报版本会分叉）")
    if re.search(r"^AppVersion=\d", text, re.M):
        out.append("AppVersion 出现了字面量版本号（应只由 CI 传入）")
    if "#error AppVersion" not in text:
        out.append("缺「漏传 AppVersion 即 #error」的硬失败")
    if "WebView2Setup" not in text:
        out.append("未内嵌 WebView2 bootstrapper")
    if "WebView2Installed" not in text:
        out.append("未按注册表判定 WebView2 是否已安装（会重复安装）")
    if "ssPostInstall" not in text:
        out.append("没有安装后置钩子（WebView2 补装接线缺失）")
    if "SignTool" in text:
        out.append("配了签名工具，但本项目明确无签名预算（SmartScreen 提示照旧）")
    return out


def _workflow_violations(text: str) -> list[str]:
    """返回 build-release.yml 的违规清单（空清单 = 通过）。"""
    out: list[str] = []
    data = yaml.safe_load(text)
    jobs = data.get("jobs", {})

    if INSTALLER_JOB not in jobs:
        out.append(f"没有 {INSTALLER_JOB} job：安装包不该挂在主 CI 上")
        return out

    job = jobs[INSTALLER_JOB]
    if job.get("needs") != "build-windows":
        out.append(f"{INSTALLER_JOB} 应当 needs: build-windows（复用已验过的便携版产物）")
    gate = str(job.get("if", ""))
    if "refs/tags/v" not in gate or "workflow_dispatch" not in gate:
        out.append(f"{INSTALLER_JOB} 的触发条件应当是「真 tag 或手动触发」（当前 {gate!r}）")
    body = yaml.safe_dump(job, allow_unicode=True)
    if "innosetup" not in body.lower() and "iscc" not in body.lower():
        out.append(f"{INSTALLER_JOB} 里没有安装 Inno Setup / 调用 ISCC")
    if INSTALLER_ARTIFACT not in body:
        out.append(f"{INSTALLER_JOB} 没有上传 {INSTALLER_ARTIFACT} artifact")
    if "verify_windows_portable.py" not in body:
        out.append(f"{INSTALLER_JOB} 没有复用真启验包闸（装完必须真起一次）")

    main = yaml.safe_dump(jobs.get("build-windows", {}), allow_unicode=True)
    if "innosetup" in main.lower() or "iscc" in main.lower():
        out.append("主 CI（build-windows）里出现了 Inno Setup ⇒ 主 CI 被装包拖慢")

    publish = jobs.get("publish-github-release", {})
    needs = publish.get("needs") or []
    if INSTALLER_JOB not in needs:
        out.append(f"发布 job 未 needs {INSTALLER_JOB}（安装包不会进 Release）")
    pub = yaml.safe_dump(publish, allow_unicode=True)
    if SETUP_GLOB not in pub:
        out.append("发布资产清单里没有 Setup.exe")
    if "未做代码签名" not in pub:
        out.append("发布正文未写明「未做代码签名」（未签名必须如实披露）")
    return out



# ── 阳性 ────────────────────────────────────────────────────────────────────
def test_installer_script_exists() -> None:
    assert ISS_PATH.exists(), f"缺少安装器脚本 {ISS_PATH.relative_to(REPO_ROOT)}"
    assert WORKFLOW_PATH.exists()


def test_installer_script_has_no_violations() -> None:
    violations = _iss_violations(ISS_PATH.read_text(encoding="utf-8"))
    assert not violations, f"安装器脚本违规：{violations}"


def test_workflow_has_no_violations() -> None:
    violations = _workflow_violations(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert not violations, f"发布流水线违规：{violations}"


def test_installer_version_matches_app_version_source() -> None:
    """安装器版本必须来自 APP_VERSION（单一真相源），不得自带字面量。"""
    iss = ISS_PATH.read_text(encoding="utf-8")
    assert "AppVersion={#AppVersion}" in iss
    assert "#error AppVersion" in iss and "#error PortableDir" in iss


def test_installer_data_dir_is_outside_install_dir() -> None:
    """数据目录（%LOCALAPPDATA%\\DeLector）不得落在安装目录（%LOCALAPPDATA%\\Programs\\DeLector）里。"""
    iss = ISS_PATH.read_text(encoding="utf-8")
    install_dir = next(ln for ln in iss.splitlines() if ln.startswith("DefaultDirName="))
    assert "{localappdata}\\Programs" in install_dir
    assert "{localappdata}\\DeLector" not in install_dir


# ── 变异自证（删掉保护物必须变红）────────────────────────────────────────────
def test_mutation_hardcoded_version_is_caught() -> None:
    text = ISS_PATH.read_text(encoding="utf-8")
    mutated = text.replace("AppVersion={#AppVersion}", "AppVersion=5.23.4")
    assert _iss_violations(mutated), "写死版本号后判据仍为空 ⇒ 死测"


def test_mutation_admin_install_is_caught() -> None:
    text = ISS_PATH.read_text(encoding="utf-8")
    mutated = text.replace("PrivilegesRequired=lowest", "PrivilegesRequired=admin")
    violations = _iss_violations(mutated)
    assert violations and any("per-user" in v for v in violations), "改成 admin 安装后判据仍为空 ⇒ 死测"


def test_mutation_uninstall_delete_is_caught() -> None:
    text = ISS_PATH.read_text(encoding="utf-8")
    mutated = text.replace("[Icons]", "[UninstallDelete]\nType: files; Name: \"{localappdata}\\DeLector\"\n\n[Icons]")
    violations = _iss_violations(mutated)
    assert violations and any("UninstallDelete" in v for v in violations), "加 [UninstallDelete] 后判据仍为空 ⇒ 死测"


def test_mutation_drop_webview2_is_caught() -> None:
    text = ISS_PATH.read_text(encoding="utf-8")
    mutated = text.replace("WebView2Installed", "NothingHere")
    violations = _iss_violations(mutated)
    assert violations and any("WebView2" in v for v in violations), "去掉 WebView2 判定后判据仍为空 ⇒ 死测"


def test_mutation_installer_job_always_runs_is_caught() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutated = text.replace(
        "if: startsWith(github.ref, 'refs/tags/v') || github.event_name == 'workflow_dispatch'",
        "if: always()",
        1,
    )
    violations = _workflow_violations(mutated)
    assert violations and any("触发条件" in v for v in violations), "去掉 tag 门后判据仍为空 ⇒ 死测"


def test_mutation_installer_in_main_job_is_caught() -> None:
    """把 Inno 步骤塞回主 CI（build-windows）必须变红——这是「别拖慢主 CI」的守卫。"""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutated = text.replace(
        "      - name: Upload Windows Artifact",
        "      - name: Install Inno Setup 6\n"
        "        run: choco install innosetup --no-progress -y\n\n"
        "      - name: Upload Windows Artifact",
        1,
    )
    violations = _workflow_violations(mutated)
    assert violations and any("主 CI" in v for v in violations), "主 CI 里出现 Inno 后判据仍为空 ⇒ 死测"


def test_mutation_drop_unsigned_disclosure_is_caught() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    mutated = text.replace("未做代码签名", "已签名")
    violations = _workflow_violations(mutated)
    assert violations and any("未做代码签名" in v for v in violations), "去掉未签名披露后判据仍为空 ⇒ 死测"
