/**
 * Service Worker for NHAI AI Road Survey Dashcam PWA.
 * Enables 100% offline shell caching when connected to Pi Direct Wi-Fi hotspot.
 */

const CACHE_NAME = "nhai-dashcam-v2.4.0";
const PRECACHE_ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./css/styles.css",
  "./js/app.js",
  "./js/live_view.js",
  "./js/gallery.js",
  "./js/telemetry.js",
  "./js/settings.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

// Install: pre-cache application shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("[ServiceWorker] Pre-caching offline shell assets");
      return cache.addAll(PRECACHE_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: purge stale caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            console.log("[ServiceWorker] Removing obsolete cache:", key);
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch: network-first for API & streams, cache-first for static shell
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Bypass cache completely for API endpoints, WebSocket, and camera streams
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws")) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        // Return cached shell, update in background
        fetch(event.request)
          .then((networkResponse) => {
            if (networkResponse && networkResponse.status === 200) {
              caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
            }
          })
          .catch(() => {});
        return cachedResponse;
      }
      return fetch(event.request);
    })
  );
});
