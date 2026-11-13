# -*- coding: utf-8 -*-
"""工作台导出必须「先落盘、后报成功」的机械闸。

缺陷背景（2026-11-11）：桌面壳 WebView2 默认 `ALLOW_DOWNLOADS=False`，
`on_download_starting` 会静默取消下载（无异常、无回调），而旧前端在 `download()`
之后无条件 `toast("已导出…")` ⇒ 磁盘无文件、界面照样报成功。

本文件钉两层：
1. `POST /api/wb/backup/save` 真的写盘，并把真实路径与字节数回给前端；
2. `tools/wb_export_probe.mjs` 切真源码逐场景跑（含 download 整体 reject / click 链抛出），
   断言 toast 只认 `res.ok`，且失败一律走 `error` 形态。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from probe_runner import ROOT as PROBE_ROOT
from probe_runner import assert_probe_clean, run_json_probe, scenario_keys


@pytest.fixture
def export_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把落盘目录指到 tmp，并确保不触发 Android 分支。"""
    import delector.routes.backup as backup_routes

    target = tmp_path / "Downloads"
    target.mkdir()
    monkeypatch.setattr(backup_routes, "_export_download_dir", lambda: (target, False))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    return target


def test_save_endpoint_writes_file_and_reports_real_path(client, export_dir: Path) -> None:
    payload = {"type": "wb-sync", "version": 1, "cards": {"der": {"word": "der"}}}
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb-sync-2026-11-11.json", "payload": payload},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    target = Path(body["path"])
    assert target.is_absolute()
    assert target.parent == export_dir
    raw = target.read_bytes()
    assert body["bytes"] == len(raw) > 0
    assert json.loads(raw.decode("utf-8")) == payload


def test_save_endpoint_never_overwrites_existing_export(client, export_dir: Path) -> None:
    req = {"filename": "wb.json", "payload": {"n": 1}}
    first = client.post("/api/wb/backup/save", json=req).json()
    second = client.post("/api/wb/backup/save", json=req).json()

    assert Path(first["path"]).name == "wb.json"
    assert Path(second["path"]).name == "wb-2.json"
    assert Path(first["path"]).is_file() and Path(second["path"]).is_file()


def test_save_endpoint_strips_path_traversal(client, export_dir: Path) -> None:
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "../../evil.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    target = Path(resp.json()["path"])
    assert target.parent == export_dir
    assert target.name == "evil.json"
    assert not (export_dir.parent / "evil.json").exists()


def test_save_endpoint_reports_failure_instead_of_fake_success(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import delector.routes.backup as backup_routes

    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(backup_routes, "_export_download_dir", lambda: (blocker, False))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 500
    assert "写入失败" in resp.json()["detail"]


def test_export_dir_is_created_when_missing(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载目录不存在时自动创建，文件必须落在新目录里。"""
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    downloads = tmp_path / "Downloads"
    assert not downloads.exists()

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert downloads.is_dir()
    assert Path(body["path"]).parent == downloads
    assert Path(body["path"]).is_file()
    assert "fallback_dir" not in body


def test_export_dir_falls_back_to_home_when_creation_fails(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载目录建不出来时退回主目录，且返回体必须能辨识这个降级。"""
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(backup_routes, "is_android", lambda: False)
    (tmp_path / "Downloads").write_text("not a directory", encoding="utf-8")

    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fallback_dir"] is True
    assert "用户主目录" in body["warning"]
    target = Path(body["path"])
    assert target.parent == tmp_path
    assert target.name == "wb.json"
    assert target.is_file()


def test_android_keeps_system_download_channel(client, export_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import delector.routes.backup as backup_routes

    monkeypatch.setattr(backup_routes, "is_android", lambda: True)
    resp = client.post(
        "/api/wb/backup/save",
        json={"filename": "wb.json", "payload": {"n": 1}},
    )

    assert resp.status_code == 501
    assert list(export_dir.iterdir()) == []


def test_export_toast_is_bound_to_probe_verified_result() -> None:
    """动态探针：成功/失败/回退/整体 reject/click 抛出的 toast 都由真实结果驱动。"""
    out = run_json_probe("wb_export_probe")
    assert_probe_clean("wb_export_probe", out)
    assert out["total"] >= 8
    assert {
        "save_ok",
        "save_ok_fallback_dir",
        "save_500",
        "save_no_path",
        "fallback_501",
        "save_network_throw",
        "download_all_reject",
        "click_reject",
    } <= scenario_keys(out)




def test_export_probe_slice_guard_scenarios_present() -> None:
    """阳性 + 防删场景：sliceFunction 的配平自证场景必须逐字在场且全绿。"""
    out = run_json_probe("wb_export_probe")
    assert_probe_clean("wb_export_probe", out)
    required = {
        "slice_real_download_has_full_body",
        "slice_real_report_has_full_body",
        "slice_skips_strings_comments_templates",
        "slice_destructured_params_full_body",
        "slice_rejects_non_brace_after_paren",
    }
    assert required <= scenario_keys(out), (
        f"wb_export_probe 缺 sliceFunction 自证场景：{sorted(required - scenario_keys(out))}"
    )


def test_export_probe_slice_guard_fails_when_balancing_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """阴性 + 变异自证：把 sliceFunction 换回旧实现 ⇒ 探针必红（判据不得恒真）。

    在 tmp 里生成变异副本（不污染 worktree），并把 ROOT 改写成仓库绝对路径，
    保证副本仍能读到 static/german/workbench.html 真源码。
    """
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.exit("CI 环境缺少必需的 node 运行时；导出探针不能以 skip 静默跳过", returncode=1)
        pytest.skip("未安装 node：本用例需要 node 跑变异副本")

    src = (PROBE_ROOT / "tools" / "wb_export_probe.mjs").read_text(encoding="utf-8")
    anchor = "function sliceFunction(src, name) {"
    assert src.count(anchor) == 1, f"注入式变异锚点应恰好 1 处，实际 {src.count(anchor)}"
    start = src.index(anchor)
    end = src.index("\nconst downloadSrc =", start)
    legacy = """function sliceFunction(src, name) {
  const start = src.indexOf("async function " + name + "(");
  if (start < 0) throw new Error("找不到 " + name);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") { depth -= 1; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error("函数未闭合：" + name);
}
"""
    root_line = 'const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");'
    assert src.count(root_line) == 1, "ROOT 锚点应恰好 1 处"
    mutant_src = (
        src[:start] + legacy + src[end:]
    ).replace(root_line, f"const ROOT = {json.dumps(str(PROBE_ROOT))};")
    mutant = tmp_path / "wb_export_probe_mutant.mjs"
    mutant.write_text(mutant_src, encoding="utf-8")

    res = subprocess.run(
        [node, str(mutant), "--json"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(PROBE_ROOT), timeout=120,
    )
    assert res.returncode != 0, "删掉配平保护物后探针仍全绿 ⇒ 判据恒真（死测）"
