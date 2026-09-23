const CACHE = 'outcome-gate-v5';
const SHELL = ['./', './index.html', './styles.css', './app.js', './manifest.webmanifest', './signatures.json', './icon.svg'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const requestUrl = new URL(event.request.url);
  if (requestUrl.origin !== self.location.origin) return;
  event.respondWith(
    fetch(event.request).then((response) => {
      if (!response.ok) return response;
      return caches.open(CACHE)
        .then((cache) => cache.put(event.request, response.clone()).then(() => response));
    }).catch(() => caches.match(event.request).then((cached) => cached || Response.error()))
  );
});
