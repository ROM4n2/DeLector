// 版本号只在这里维护一处，与 android/app/build.gradle 的 fallback 对齐
// （test_writer_mobile.py 断言两者一致）。CACHE_NAME 一变，activate 就清掉旧缓存。
const CACHE_NAME = "delector-static-v5.23.5";

// 缓存策略（2026-11-07 明确）：
//   在线 ⇒ 永远以网络响应为准（network-first，且要求 HTTP 缓存回源校验）；
//   离线 ⇒ 才回落到上一次成功响应。离线时当然只能看到旧内容，这是离线能力的代价，
//          不是「旧缓存遮蔽新版本」——一旦恢复在线，下一次请求就会覆盖缓存。
//
// 生效路径（不要含糊）：
//   - 新 sw.js：下一次导航/注册检查时被发现，install 后 skipWaiting + activate 立即接管；
//     已在运行的页面不会被强制替换，页面收到 delector-update 后显示「立即刷新」。
//   - 静态文件：下一次成功导航即拿到新内容；正在运行的页面要刷新才换掉已加载的 JS。
//   - Android 装机/覆盖安装：见 MainActivity.syncStaticAssets —— 新资产在**下次启动**
//     解包（服务器启动前完成），本次运行中的页面刷新也无法越过那次解包。
//
// 这里曾有一份 STATIC_ASSETS 预缓存清单，v4.4.5 删除：install 从来只调 skipWaiting()、
// 没有 cache.addAll，那份清单一行都没执行过。更糟的是它把带版本查询串的 URL
// 写成缓存键，而真实请求不带查询串，永远匹配不上——留着只会让人以为预缓存生效了。
// 实际缓存由下面的 fetch 处理器边走边填。

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Clean old caches
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        }),
      );
      // Claim all clients immediately
      await self.clients.claim();
      // 温和更新：不无条件 client.navigate 全窗硬刷（会丢未保存状态），
      // 只广播“新版本已就绪”，由页面侧提示用户自行刷新。
      const wins = await self.clients.matchAll({ type: "window" });
      wins.forEach((win) => win.postMessage({ type: "delector-update" }));
    })(),
  );
});

// 页面侧发现「构建戳 ≠ 磁盘指纹」时发来的清缓存指令。只有在线才可能发得出来，
// 所以这里直接清空全部缓存；下一次请求会按 network-first 重新填充。
self.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "delector-purge-cache") return;
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
      const source = event.source;
      if (source && typeof source.postMessage === "function") {
        source.postMessage({
          type: "delector-purge-done",
          fingerprint: event.data.fingerprint || "",
        });
      }
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  // Pass API requests straight through
  if (request.url.includes("/api/")) {
    return;
  }
  if (request.method !== "GET") {
    return;
  }
  event.respondWith(networkFirst(event, request));
});

/**
 * 在线以网络为准；网络失败才读缓存。
 *
 * `cache: "no-cache"` 让浏览器 HTTP 缓存也强制回源校验（服务端本身已发
 * Cache-Control: no-cache，这里是第二道保险：即使某条静态路由漏了响应头，
 * SW 也不会拿 HTTP 缓存里的旧副本冒充网络结果）。
 */
async function networkFirst(event, request) {
  try {
    const response = await fetch(request, { cache: "no-cache" });
    if (response && response.status === 200 && response.type === "basic") {
      const copy = response.clone();
      event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)),
      );
    }
    return response;
  } catch (error) {
    // 2026-11-13 审计 P1 #4：只从**当前** CACHE_NAME 回落。
    // `caches.match()` 默认跨所有 cache 搜索：覆盖安装后旧 SW 仍可能控制首帧，
    // 它会命中旧 CACHE_NAME 里的旧 JS 并当成 200 交付 —— 页面跑在新服务端的旧壳上。
    // 旧 cache 的正确归宿是 activate 里的清理，不是 fetch 的兜底。
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request);
    if (cached) return cached;
    // 导航请求仍回落应用外壳：Android WebView 首帧（实测 ≈0.5s）必然早于
    // 进程内服务就绪（实测 python_start_done ≈1.4s），不回落会直接停在
    // net::ERR_FAILED 错误页 —— 2026-11-13 模拟器实测证伪了「在线未就绪不回落」。
    // 旧壳的版本失配由页面侧 build-stamp 自检触发清缓存 + 刷新，不在这里拦。
    if (request.mode === "navigate") {
      const shell = await cache.match("/");
      if (shell) return shell;
    }
    throw error;
  }
}
