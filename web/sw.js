/* TAUROS PWA service worker — shell offline, API network-first */
const CACHE = "tauros-shell-v1";
const SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/icon-180.png",
  "/offline.html",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isApi(url) {
  const path = url.pathname;
  if (path.startsWith("/static/")) return false;
  if (path === "/" || path === "/index.html") return false;
  if (path === "/manifest.webmanifest" || path === "/sw.js") return false;
  // health and API JSON
  return (
    path.startsWith("/chat") ||
    path.startsWith("/memories") ||
    path.startsWith("/open-loops") ||
    path.startsWith("/decisions") ||
    path.startsWith("/audit") ||
    path.startsWith("/export") ||
    path.startsWith("/security") ||
    path.startsWith("/dashboard") ||
    path.startsWith("/tools") ||
    path.startsWith("/health") ||
    path.startsWith("/writes") ||
    path.startsWith("/privileges") ||
    path.startsWith("/brief") ||
    path.startsWith("/auth")
  );
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (isApi(url)) {
    // Network only for API (auth + freshness)
    event.respondWith(
      fetch(req).catch(
        () =>
          new Response(JSON.stringify({ ok: false, offline: true, detail: "Offline" }), {
            status: 503,
            headers: { "Content-Type": "application/json" },
          })
      )
    );
    return;
  }

  // App shell: network first, cache fallback
  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy));
        return res;
      })
      .catch(() =>
        caches.match(req).then((hit) => hit || caches.match("/") || caches.match("/index.html"))
      )
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skipWaiting") self.skipWaiting();
});
