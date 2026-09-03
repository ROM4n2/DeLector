// 版本号只在这里维护一处，与 android/app/build.gradle 的 fallback 对齐
// （test_writer_mobile.py 断言两者一致）。CACHE_NAME 一变，activate 就清掉旧缓存。
const CACHE_NAME = "delector-static-v5.0.2";

// 这里曾有一份 STATIC_ASSETS 预缓存清单，v4.4.5 删除：install 从来只调 skipWaiting()、
// 没有 cache.addAll，那份清单一行都没执行过。更糟的是它把带版本查询串的 URL
// 写成缓存键，而真实请求不带查询串，永远匹配不上——留着只会让人以为预缓存生效了。
// 实际缓存由下面的 fetch 处理器边走边填。

self.addEventListener("install", (event) => {
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

self.addEventListener("fetch", (event) => {
  // Pass API requests straight through
  if (event.request.url.includes("/api/")) {
    return;
  }
  // Network first, cache fallback to avoid stale code in dev
  event.respondWith(
    fetch(event.request)
      .then((fetchRes) => {
        if (event.request.method === "GET" && fetchRes.status === 200) {
          const resClone = fetchRes.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, resClone);
          });
        }
        return fetchRes;
      })
      .catch(() => caches.match(event.request)),
  );
});
