const CACHE_NAME = 'delector-static-v3.4.1';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/style.css?v=3.4.1',
  '/js/main.js?v=3.4.1',
  '/js/core.js',
  '/js/player.js',
  '/js/reader.js',
  '/js/cards.js',
  '/js/folio.js',
  '/js/cloze.js',
  '/manifest.json'
];




self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) return caches.delete(key);
        })
      );
    })
  );
  self.clients.claim();
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
