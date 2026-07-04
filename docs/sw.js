/* CryptoEdge Service Worker — App-Shell cachen, Daten network-first (frisch wenn online). */
const C = "cryptoedge-v1";
const SHELL = ["./", "./index.html", "./app.js", "./manifest.webmanifest",
  "./icon-192.png", "./icon-512.png", "./apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(C).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== C).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.endsWith(".json")) {
    // Daten: erst Netz (frisch), sonst Cache (offline).
    e.respondWith(fetch(e.request).then((r) => {
      const cp = r.clone(); caches.open(C).then((c) => c.put(e.request, cp)); return r;
    }).catch(() => caches.match(e.request)));
  } else {
    // Shell: erst Cache (schnell), sonst Netz.
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
