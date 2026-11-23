/* Bratanki service worker (v13, v16: képek). Az alkalmazás héja hálózat-először, tartalék a gyorsítótár;
   a hangcsomagok (az a/ mappa verziózott csomagjai) változatlanok, ezért gyorsítótár-először; a betűtípusok a háttérben frissülnek. */
var V = '8ca029b9a9', SHELL = 'bratanki-shell-' + V, AUDIO = 'bratanki-audio', FONTS = 'bratanki-fonts', IMG = 'bratanki-img';
var CORE = ['./', 'index.html', 'manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png', 'a/index.json'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(SHELL).then(function (c) { return c.addAll(CORE); }).then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (ks) {
    return Promise.all(ks.filter(function (k) { return k.indexOf('bratanki-shell-') === 0 && k !== SHELL; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
function netFirst(req, cacheName) {
  return fetch(req).then(function (r) {
    if (r && r.ok) { var cp = r.clone(); caches.open(cacheName).then(function (c) { c.put(req, cp); }); }
    return r;
  }, function () { return caches.match(req, { ignoreSearch: true }).then(function (m) { return m || caches.match('index.html'); }); });
}
function cacheFirst(req, cacheName) {
  return caches.open(cacheName).then(function (c) {
    return c.match(req).then(function (m) {
      return m || fetch(req).then(function (r) { if (r && r.ok) c.put(req, r.clone()); return r; });
    });
  });
}
function swr(req, cacheName) {
  return caches.open(cacheName).then(function (c) {
    return c.match(req).then(function (m) {
      var f = fetch(req).then(function (r) { if (r && (r.ok || r.type === 'opaque')) c.put(req, r.clone()); return r; }, function () { return m; });
      return m || f;
    });
  });
}
self.addEventListener('fetch', function (e) {
  var req = e.request; if (req.method !== 'GET') return;
  var u = new URL(req.url);
  if (u.origin === self.location.origin) {
    if (/\/a\/v\d+\/[^/]+$/.test(u.pathname)) { e.respondWith(cacheFirst(req, AUDIO)); return; }
    if (/\/k\/[^/]+\.webp$/.test(u.pathname)) { e.respondWith(cacheFirst(req, IMG)); return; } // v16: a kánon képei (?v= verzióval)
    e.respondWith(netFirst(req, SHELL)); return;
  }
  if (u.hostname === 'fonts.googleapis.com' || u.hostname === 'fonts.gstatic.com') { e.respondWith(swr(req, FONTS)); return; }
  if (u.hostname === 'upload.wikimedia.org' && u.pathname.indexOf('/thumb/') >= 0) { e.respondWith(cacheFirst(req, IMG)); return; } // v16.1: a Kánon távoli képei
});
