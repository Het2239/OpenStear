// Service worker: makes OpenSteer installable and lets the shell open while
// the PC is starting up. Network first, so updates from the PC always win;
// the cache is only a fallback.

const CACHE = "opensteer-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin ||
      url.pathname === "/ws" || url.pathname === "/health") return;
  e.respondWith((async () => {
    try {
      const res = await fetch(e.request);
      if (res.ok) (await caches.open(CACHE)).put(e.request, res.clone());
      return res;
    } catch (err) {
      const cached = await caches.match(e.request, { ignoreSearch: true });
      if (cached) return cached;
      throw err;
    }
  })());
});
