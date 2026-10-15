// Fundamento B3: rede primeiro (sempre a versão mais nova), cache como reserva para abrir sem internet.
const CACHE = "fundamento-v1";
const BASE = ["./", "./index.html", "./manifest.webmanifest", "./acoes.json", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(BASE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (r.ok) { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copia)); }
        return r;
      })
      .catch(() => caches.match(url.pathname).then((r) => r || caches.match("./index.html")))
  );
});
