// Fundamento B3: rede primeiro (sempre a versão mais nova), cache como reserva para abrir sem internet.
const CACHE = "fundamento-v3";
const BASE = ["./", "./index.html", "./manifest.webmanifest", "./acoes.json", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  // o essencial entra no cache de uma vez; os dados leves vão em separado e uma falha neles não impede a instalação
  const EXTRA = ["./dados/fiis.json", "./dados/agenda.json", "./dados/referencias.json", "./dados/fiis_imoveis.json"];
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(BASE).then(() => Promise.allSettled(EXTRA.map((u) => c.add(u))))).then(() => self.skipWaiting()));
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
    fetch(e.request, {cache: "no-cache"})
      .then((r) => {
        if (r.ok) { const copia = r.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copia)); }
        return r;
      })
      .catch(() => caches.match(url.pathname).then((r) => r || caches.match("./index.html")))
  );
});
