// Service Worker — 离线缓存策略
//
// ⚠️ 分工是有意为之，别把两者换回来：
//   静态资源（页面/图标/echarts）→ 缓存优先，秒开
//   data.json（每天被 Actions 改写）→ **网络优先**，否则永远慢一个版本
// 历史坑：data.json 原先是「预缓存 + 缓存优先」，返回访客每次都会先看到上一次的数据，
// 页面上的表现就是「今天调价的那一轮不见了」，必须刷第二次才出来。
// 注意 index.html 里的 fetch('./data.json', {cache:'no-cache'}) **绕不过** Cache Storage ——
// no-cache 只作用在 HTTP 缓存上，caches.match() 照样命中。所以必须在 SW 这层改。
const CACHE_NAME = 'fuel-price-tracker-v4';
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './favicon.png',
  './icon-192x192.png',
  './icon-512x512.png',
  './hero-jinan.webp',
  './hero-jinan.jpg',
  'https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js',
];

const DATA_FILE = 'data.json';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        CORE_ASSETS.map((url) =>
          cache.add(url).catch((err) => console.warn('[SW] Cache miss:', url, err))
        )
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // 只处理 GET 请求
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // ---- 数据文件：网络优先，断网才回退缓存 ----
  if (url.pathname.endsWith('/' + DATA_FILE)) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() =>
          caches.match(event.request, { ignoreSearch: true }).then(
            (cached) => cached || Response.error()
          )
        )
    );
    return;
  }

  // ---- 其余静态资源：缓存优先，同时后台更新 ----
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetchPromise = fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => null);

      return cached || fetchPromise;
    })
  );
});
