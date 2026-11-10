/* TW Trades does not cache API responses or use stale offline price fallbacks. */
self.addEventListener("install", event => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(key => key.startsWith("tw-trades-")).map(key => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  if (event.request.method !== "GET") return;
  // Network-only for every request: no cache writes and no cached response fallback.
  event.respondWith(fetch(event.request, { cache: "no-store" }));
});
