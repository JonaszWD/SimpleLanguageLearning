// Offline shell. The build prepends `self.__BUILD__ = { version, shell }` (backend/app/build.py):
// version = hash of all app files, shell = every file to precache (paths relative to this file).
// No manual bumping, and no assumption about where the app is hosted ("/" or "/<repo>/").
const BUILD = self.__BUILD__ || { version: "dev", shell: [] };
const CACHE = `app-${BUILD.version}`;
const scope = self.registration.scope;
const shellUrls = BUILD.shell.map((p) => new URL(p, scope).href);
// Dynamic or large content is never part of the shell.
const bypass = ["api/", "packs/", "articles/"].map((p) => new URL(p, scope).pathname);

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(shellUrls.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (e) => {
  if (e.data === "version") e.ports[0]?.postMessage(BUILD.version);
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || bypass.some((p) => url.pathname.startsWith(p))) return;
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request)),
  );
});
