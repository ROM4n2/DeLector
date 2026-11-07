// @ts-check
/* DeLector - 前端资源自证：把「页面里跑的到底是哪一版静态资源」变成可判断的值。
 *
 * 三个指纹：
 *   html   —— 构建时随 index.html 一起落地的 <meta name="delector-assets">；
 *   js     —— 构建时写进本模块的 BUILD_STAMP（证明加载到的 JS 也是这一版）；
 *   server —— 运行时 /api/health 现算的磁盘内容指纹。
 *
 * 三者相等 ⇒ 页面跑的就是磁盘上的这一份资源。
 * 任一不相等 ⇒ 对应层是旧的（HTTP 缓存 / 旧 Service Worker / 没解包新资产），
 *              页面会显式提示并请求 SW 清缓存，**不需要用户手动清任何东西**。
 * 没有戳（开发态 / 未打构建戳）⇒ 不告警，只用 server 值给自己贴标签。
 *
 * 读数入口（页面侧可读）：
 *   document.documentElement.dataset.assetsFingerprint
 *   document.documentElement.dataset.pageAssets / dataset.jsAssets / dataset.serverAssets
 *   window.DeLectorBuild
 */
"use strict";

// 构建期由 tools/sync_android_sources.py 改写为资源指纹；仓库源保持空串（开发态）。
// 它让「HTML 是新的、但 main.js/build-stamp.js 还是旧缓存」这一层也能被抓到。
export const BUILD_STAMP = "";

const META_NAME = "delector-assets";
const PLACEHOLDER = "__DELECTOR_ASSETS__";
const BAR_ID = "delector-assets-bar";

/** 读取构建时注入的页面指纹；占位符/缺省都视为「没有戳」。 */
export function readPageFingerprint(doc = document) {
  const el = doc.querySelector('meta[name="' + META_NAME + '"]');
  if (!el) return "";
  const value = (el.getAttribute("content") || "").trim();
  return value && value !== PLACEHOLDER ? value : "";
}

/** 失配提示条：复用更新条的文案语气，但样式内联，避免改动 style.css。 */
function showMismatchBar(html, js, server, reload) {
  if (document.getElementById(BAR_ID)) return;
  const bar = document.createElement("div");
  bar.id = BAR_ID;
  bar.setAttribute("role", "status");
  bar.style.cssText =
    "position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:99999;" +
    "display:flex;gap:10px;align-items:center;max-width:92vw;padding:10px 14px;" +
    "border-radius:10px;background:#1b1e28;color:#fff;font-size:13px;" +
    "line-height:1.5;box-shadow:0 6px 24px rgba(0,0,0,.28);";

  const text = document.createElement("span");
  // textContent 而不是 innerHTML：两个值来自网络/构建产物，不参与 HTML 解析。
  text.textContent =
    "页面资源与磁盘不一致（HTML " +
    (html || "-") +
    " / JS " +
    (js || "-") +
    " / 磁盘 " +
    (server || "-") +
    "），当前可能是旧界面。";
  text.style.cssText = "flex:1 1 auto;min-width:0;";

  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.textContent = "立即刷新";
  refresh.style.cssText =
    "flex:0 0 auto;padding:4px 10px;border:0;border-radius:6px;cursor:pointer;" +
    "background:#e2574c;color:#fff;font-size:13px;";
  refresh.addEventListener("click", reload);

  const later = document.createElement("button");
  later.type = "button";
  later.textContent = "稍后";
  later.style.cssText =
    "flex:0 0 auto;padding:4px 10px;border:0;border-radius:6px;cursor:pointer;" +
    "background:transparent;color:#cfc7ba;font-size:13px;";
  later.addEventListener("click", () => bar.remove());

  bar.appendChild(text);
  bar.appendChild(refresh);
  bar.appendChild(later);
  (document.body || document.documentElement).appendChild(bar);
}

export function initBuildStamp(options = {}) {
  const doFetch = options.fetchImpl || globalThis.fetch;
  const reload = options.reload || (() => globalThis.location.reload());
  const root = document.documentElement;
  const html = readPageFingerprint();
  const js = BUILD_STAMP && BUILD_STAMP !== PLACEHOLDER ? BUILD_STAMP.trim() : "";
  if (html) root.setAttribute("data-page-assets", html);
  if (js) root.setAttribute("data-js-assets", js);
  if (html || js) root.setAttribute("data-assets-fingerprint", html || js);
  if (typeof doFetch !== "function") return Promise.resolve(null);

  return doFetch("/api/health", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  })
    .then((resp) => (resp && resp.ok ? resp.json() : null))
    .then((data) => {
      const server =
        data && typeof data.assets_fingerprint === "string" ? data.assets_fingerprint : "";
      if (server) root.setAttribute("data-server-assets", server);
      root.setAttribute("data-assets-fingerprint", html || js || server);
      globalThis.DeLectorBuild = {
        version: data && data.version ? data.version : "",
        html,
        js,
        server,
      };
      // 控制台是「没有控制台之外仪表」时最快的一条取证通道。
      console.info(
        "[DeLector] assets html=" +
          (html || "(none)") +
          " js=" +
          (js || "(none)") +
          " disk=" +
          (server || "(unknown)"),
      );
      const stamps = [html, js].filter(Boolean);
      const stale = Boolean(server) && stamps.some((stamp) => stamp !== server);
      if (!stale) return null;

      // 失配：先把旧 SW 缓存清掉（在线才可能走到这里），再提示用户刷新。
      try {
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
          navigator.serviceWorker.controller.postMessage({
            type: "delector-purge-cache",
            fingerprint: server,
          });
        }
      } catch (_) {
        // SW 不可用不影响判断本身。
      }
      showMismatchBar(html, js, server, reload);
      return { html, js, server, stale: true };
    })
    .catch(() => null);
}
