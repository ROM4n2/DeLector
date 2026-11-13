# -*- coding: utf-8 -*-
"""静态资源更新链路的守卫：指纹可读、SW 不吃旧缓存、APK 资产新鲜度可判定。"""

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from delector.core.assets_manifest import (
    compute_assets_fingerprint,
    inject_js_stamp,
    inject_stamp_meta,
)

ROOT = Path(__file__).resolve().parent.parent


def _load_sync_tool():
    spec = importlib.util.spec_from_file_location(
        "sync_android_sources", ROOT / "tools" / "sync_android_sources.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_health_reports_asset_fingerprint(client):
    from delector import server

    body = client.get("/api/health").json()
    fingerprint = body.get("assets_fingerprint")
    assert isinstance(fingerprint, str) and len(fingerprint) == 12, (
        f"/api/health 必须暴露 12 位静态资源指纹，实际 {fingerprint!r}"
    )
    assert fingerprint == compute_assets_fingerprint(server.STATIC_DIR), (
        "health 指纹必须与磁盘内容一致；否则页面失配提示会撒谎"
    )


def test_service_worker_is_network_first_and_purges_on_request():
    sw = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")

    # 在线必须回源（且强制 HTTP 缓存校验），旧缓存只能作为离线兜底。
    assert 'fetch(request, { cache: "no-cache" })' in sw
    assert "async function networkFirst" in sw
    # 页面发现指纹失配时能请求清缓存；不要求用户手动操作。
    assert 'event.data.type !== "delector-purge-cache"' in sw
    # 不允许退回 cache-first：先 fetch 再回落，且回落只走**当前** CACHE_NAME。
    assert sw.index("await fetch(request") < sw.index("await caches.open(CACHE_NAME)")
    # 跨 cache 回落必须已移除（旧 `caches.match(request)` 会命中旧版本 cache，
    # 把覆盖安装前的旧 JS 当 200 交付 —— 2026-11-13 审计 P1 #4）。
    assert "caches.match(request)" not in sw


def test_service_worker_registration_bypasses_http_cache():
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert 'navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" })' in main_js


def test_page_imports_build_stamp_self_check():
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert 'from "./build-stamp.js"' in main_js
    assert "initBuildStamp();" in main_js

    build_stamp = (ROOT / "static" / "js" / "build-stamp.js").read_text(encoding="utf-8")
    # 页面侧读数入口必须稳定存在（验证步骤直接读它们）。
    assert "data-assets-fingerprint" in build_stamp
    assert "DeLectorBuild" in build_stamp
    assert '"/api/health"' in build_stamp
    # JS 戳：HTML 刷新但 JS 仍旧时也能判定。
    assert 'export const BUILD_STAMP = "";' in build_stamp


def _make_repo_and_android(tmp_path: Path):
    repo_root = tmp_path / "repo"
    static = repo_root / "static"
    (static / "js").mkdir(parents=True)
    (static / "index.html").write_text(
        "<!DOCTYPE html><html><head><title>x</title></head><body></body></html>",
        encoding="utf-8",
    )
    (static / "style.css").write_text(":root{--a:1}", encoding="utf-8")
    (static / "js" / "main.js").write_text("export const a = 1;", encoding="utf-8")
    (static / "js" / "build-stamp.js").write_text(
        'export const BUILD_STAMP = "";', encoding="utf-8"
    )

    android_root = tmp_path / "android"
    python_dest = android_root / "app" / "src" / "main" / "python"
    (python_dest / "delector").mkdir(parents=True)
    (python_dest / "delector" / "server.py").write_text("x = 1", encoding="utf-8")
    (python_dest / "start.py").write_text("x = 1", encoding="utf-8")
    (python_dest / "de_core_news_sm").mkdir()
    (python_dest / "de_core_news_sm" / "meta.json").write_text("{}", encoding="utf-8")
    (python_dest / "de_core_news_sm-3.7.0.dist-info").mkdir()
    (python_dest / "de_core_news_sm-3.7.0.dist-info" / "METADATA").write_text(
        "Name: x", encoding="utf-8"
    )

    static_dest = android_root / "app" / "src" / "main" / "assets" / "static"
    shutil.copytree(static, static_dest)
    fingerprint = compute_assets_fingerprint(static, use_cache=False)
    (static_dest / "asset-fingerprint.txt").write_text(fingerprint, encoding="utf-8")
    inject_stamp_meta(static_dest / "index.html", fingerprint)
    inject_js_stamp(static_dest / "js" / "build-stamp.js", fingerprint)
    return repo_root, android_root, fingerprint


def test_android_sync_check_rejects_stale_packaged_assets(tmp_path):
    tool = _load_sync_tool()
    repo_root, android_root, fingerprint = _make_repo_and_android(tmp_path)

    tool.check(android_root, repo_root)  # 同步一致时通过

    # 仓库 CSS 改了但没重跑同步 ⇒ 必须能判定为旧包（而不是靠人眼）。
    (repo_root / "static" / "style.css").write_text(":root{--a:2}", encoding="utf-8")
    with pytest.raises(tool.SyncError, match="静态资源已过期"):
        tool.check(android_root, repo_root)

    # 重跑同步（这里等价于按新内容重写标记）后恢复通过。
    new_fingerprint = compute_assets_fingerprint(repo_root / "static", use_cache=False)
    assert new_fingerprint != fingerprint
    (android_root / "app" / "src" / "main" / "assets" / "static" / "asset-fingerprint.txt").write_text(
        new_fingerprint, encoding="utf-8"
    )
    shutil.rmtree(android_root / "app" / "src" / "main" / "assets" / "static")
    shutil.copytree(repo_root / "static", android_root / "app" / "src" / "main" / "assets" / "static")
    (android_root / "app" / "src" / "main" / "assets" / "static" / "asset-fingerprint.txt").write_text(
        new_fingerprint, encoding="utf-8"
    )
    inject_stamp_meta(
        android_root / "app" / "src" / "main" / "assets" / "static" / "index.html",
        new_fingerprint,
    )
    inject_js_stamp(
        android_root / "app" / "src" / "main" / "assets" / "static" / "js" / "build-stamp.js",
        new_fingerprint,
    )
    tool.check(android_root, repo_root)


SW_FALLBACK_PROBE = r"""
const fs = require('fs');
const src = fs.readFileSync('static/sw.js', 'utf8');
const m = src.match(/const CACHE_NAME = "([^"]+)"/);
if (!m) { console.log(JSON.stringify({ fatal: 'CACHE_NAME not found' })); process.exit(0); }
const nameCur = m[1];
const nameOld = nameCur.replace(/v[\d.]+$/, 'v0.0.0');

// 旧 cache 里有同名旧资源；当前 cache 为空。fetch 失败 ⇒ 走 catch。
const selfObj = {
  addEventListener() {},
  skipWaiting() {},
  clients: { claim: async () => {}, matchAll: async () => [] },
  navigator: { onLine: true }, // 在线但服务未就绪
};
const cachesObj = {
  keys: async () => [nameOld, nameCur],
  delete: async () => true,
  open: async (name) => ({
    put: async () => {},
    match: async (r) => (name === nameCur ? undefined : (String(r.url || r) === '/js/x.js' ? 'OLD' : undefined)),
  }),
  // 旧实现用的跨 cache 语义：任何 cache 命中都算。
  match: async (r) => (String(r.url || r) === '/js/x.js' ? 'OLD' : undefined),
};
const offlineFetch = async () => { throw new Error('offline'); };
const fn = new Function('self', 'caches', 'fetch', src + '\n; return networkFirst;')(selfObj, cachesObj, offlineFetch);
(async () => {
  let outcome;
  try { outcome = await fn({ waitUntil() {} }, { url: '/js/x.js', mode: 'no-cors' }); }
  catch (e) { outcome = 'THREW'; }
  console.log(JSON.stringify({ outcome, cacheName: nameCur, nameOld }));
})();
"""


def test_service_worker_fallback_does_not_cross_cache_versions() -> None:
    """行为探针：旧 CACHE_NAME 里的资源不得被 catch 当离线兜底返回。

    2026-11-13 审计 P1 #4：`caches.match(request)` 跨所有 cache 搜索，覆盖安装后
    旧 SW 会把旧 cache 里的旧 JS 当 200 交付。这里在 node 里 mock self/caches/fetch，
    真调 `networkFirst`：当前 cache 为空 + 旧 cache 有同名资源 + fetch 失败（在线），
    正确行为是抛错（交给就绪探针补载），而不是返回 'OLD'。
    """
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.exit("CI 缺少 node：SW 缓存回落探针不能静默跳过", returncode=1)
        pytest.skip("未安装 node：本探针需要 node 执行真实 networkFirst")
    assert node is not None  # 类型收窄：pytest.skip 不被 mypy 当作 NoReturn
    proc = subprocess.run(
        [node, "-e", SW_FALLBACK_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        timeout=60,
    )
    assert proc.returncode == 0, f"node 探针自身失败：{proc.stderr[-1500:]}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "fatal" not in payload, payload
    assert payload["outcome"] != "OLD", (
        "catch 跨 cache 命中了旧版本资源并当 200 交付："
        f"nameOld={payload['nameOld']} nameCur={payload['cacheName']}"
    )
    assert payload["outcome"] == "THREW", payload
