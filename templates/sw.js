// AAMO Service Worker — cache-first para estáticos, network-first para páginas
const CACHE = 'aamo-v1';

const PRECACHE = [
    '/static/img/Milton-Ochoa.png',
    '/static/img/logo_color.png',
];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE).then(c => c.addAll(PRECACHE)).catch(() => {})
    );
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    const { request } = e;
    if (request.method !== 'GET') return;
    if (!request.url.startsWith(self.location.origin)) return;

    const url = new URL(request.url);

    if (url.pathname.startsWith('/static/')) {
        // Estáticos: cache-first (whitenoise ya sirve con hash en prod)
        e.respondWith(
            caches.match(request).then(cached =>
                cached || fetch(request).then(resp => {
                    if (resp.ok) {
                        caches.open(CACHE).then(c => c.put(request, resp.clone()));
                    }
                    return resp;
                })
            )
        );
        return;
    }

    // Páginas: network-first, fallback a caché (lectura offline del cronograma)
    e.respondWith(
        fetch(request)
            .then(resp => {
                if (resp.ok) {
                    caches.open(CACHE).then(c => c.put(request, resp.clone()));
                }
                return resp;
            })
            .catch(() => caches.match(request))
    );
});
