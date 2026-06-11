const CACHE = 'lsams-v1';
const OFFLINE_URL = '/gabay/app';

const PRECACHE = [
  '/gabay/app',
  '/gabay/app/leads',
  '/static/icons/icon-192.png',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;

  // CDN assets — cache first
  if (e.request.url.includes('cdn.jsdelivr.net') || e.request.url.includes('unpkg.com')) {
    e.respondWith(
      caches.match(e.request).then(cached => cached || fetch(e.request).then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      }))
    );
    return;
  }

  // App pages — network first, fall back to cache
  if (e.request.url.includes(self.location.origin)) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
          return res;
        })
        .catch(() => caches.match(e.request).then(cached => cached || caches.match(OFFLINE_URL)))
    );
  }
});

// Background sync for offline visit submissions
self.addEventListener('sync', e => {
  if (e.tag === 'sync-visits') {
    e.waitUntil(syncPendingVisits());
  }
});

async function syncPendingVisits() {
  const db = await openDB();
  const tx = db.transaction('pending_visits', 'readwrite');
  const store = tx.objectStore('pending_visits');
  const all = await store.getAll();
  for (const visit of all) {
    try {
      await fetch('/visits/new/' + visit.lead_id, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(visit.data)
      });
      await store.delete(visit.id);
    } catch (_) { /* will retry next sync */ }
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('lsams', 1);
    req.onupgradeneeded = e => e.target.result.createObjectStore('pending_visits', { keyPath: 'id', autoIncrement: true });
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}
