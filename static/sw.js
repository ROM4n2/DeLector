// 版本号只在这里维护一处，与 android/app/build.gradle 的 fallback 对齐
// （test_writer_mobile.py 断言两者一致）。CACHE_NAME 一变，activate 就清掉旧缓存。
const CACHE_NAME = 'delector-static-v4.5.0';

// 这里曾有一份 STATIC_ASSETS 预缓存清单，v4.4.5 删除：install 从来只调 skipWaiting()、
// 没有 cache.addAll，那份清单一行都没执行过。更糟的是它把带版本查询串的 URL
// 写成缓存键，而真实请求不带查询串，永远匹配不上——留着只会让人以为预缓存生效了。
// 实际缓存由下面的 fetch 处理器边走边填。

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Clean old caches
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
      );
      // Claim all clients immediately
      await self.clients.claim();
      // Force reload all pages to pick up new assets
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach((client) => {
        client.navigate(client.url);
      });
    })()
  );
});

self.addEventListener('fetch', (event) => {
  // Pass API requests straight through
  if (event.request.url.includes('/api/')) {
    return;
  }
  // Network first, cache fallback to avoid stale code in dev
  event.respondWith(
    fetch(event.request)
      .then((fetchRes) => {
        if (event.request.method === 'GET' && fetchRes.status === 200) {
          const resClone = fetchRes.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, resClone);
          });
        }
        return fetchRes;
      })
      .catch(() => caches.match(event.request))
  );
});
