/* TW Trades deliberately does not cache market/API responses.
   Offline pages must never masquerade as current prices or live analysis. */
const CACHE_NAME = "tw-trades-network-only-v2";

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
  // Pass every request through to the network. No cache writes and no stale fallback.
  event.respondWith(fetch(event.request, { cache: "no-store" }));
});
