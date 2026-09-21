/* 简单 service worker：离线缓存静态资源（阶段2 骨架版）。
   策略：安装时预缓存构建产物清单（由构建注入 __WB_MANIFEST__，
   未注入则退化为仅缓存应用外壳）；运行时缓存优先（cache-first）。 */
const CACHE = 'assignment-assistant-v1'
const BASE = new URL(self.registration.scope)

self.addEventListener('install', (event) => {
  const core = [
    new URL('./', BASE).href,
    new URL('./index.html', BASE).href,
    new URL('./manifest.webmanifest', BASE).href,
    new URL('./icons/icon.svg', BASE).href,
  ]
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      Promise.allSettled(core.map((u) => cache.add(u)))
    ).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  // 仅缓存同源资源；引擎/LLM 等跨域请求直接放行
  if (url.origin !== self.location.origin) return
  // 导航请求（含 index.html）一律 network-first（D21 修订）：保证部署更新
  // 到 App 后能在下次启动拿到新版本，不会长期停留在旧缓存 UI。
  const isNav = req.mode === 'navigate' ||
                url.pathname.endsWith('/index.html') ||
                url.pathname === new URL('./', BASE).pathname
  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit && !isNav) return hit
      return fetch(req)
        .then((res) => {
          if (res.ok && url.href.startsWith(BASE.href)) {
            const copy = res.clone()
            caches.open(CACHE).then((cache) => cache.put(req, copy))
          }
          return res
        })
        .catch(() => caches.match(new URL('./index.html', BASE).href))
    })
  )
})
