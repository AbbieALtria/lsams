const CACHE = 'lsams-v2';
const OFFLINE_URL = '/gabay/app';

const PRECACHE = [
  '/gabay/app',
  '/gabay/app/leads',
  '/gabay/app/leads-json',
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

  // Leads JSON — cache first (for offline use), refresh in background
  if (e.request.url.includes('/gabay/app/leads-json')) {
    e.respondWith(
      caches.open(CACHE).then(cache =>
        cache.match(e.request).then(cached => {
          const fetchPromise = fetch(e.request).then(res => {
            cache.put(e.request, res.clone());
            return res;
          });
          return cached || fetchPromise;
        })
      )
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
      const res = await fetch('/gabay/app/checkin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(visit.data)
      });
      if (res.ok || res.redirected) {
        const tx2 = db.transaction('pending_visits', 'readwrite');
        await tx2.objectStore('pending_visits').delete(visit.id);
        // Notify all open clients
        self.clients.matchAll().then(clients =>
          clients.forEach(c => c.postMessage({ type: 'sync_complete', count: all.length }))
        );
      }
    } catch (_) { /* will retry next sync */ }
  }
}

// Push notification handler
self.addEventListener('push', e => {
  let data = { title: 'LSAMS', body: 'You have a new update.' };
  try { data = e.data.json(); } catch (_) {}
  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: { url: data.url || '/gabay/app' },
      vibrate: [200, 100, 200],
      tag: 'lsams-notif',
      renotify: true,
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = e.notification.data?.url || '/gabay/app';
  e.waitUntil(
    self.clients.matchAll({ type: 'window' }).then(clients => {
      const existing = clients.find(c => c.url.includes(self.location.origin));
      if (existing) { existing.focus(); existing.navigate(url); }
      else self.clients.openWindow(url);
    })
  );
});

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('lsams', 1);
    req.onupgradeneeded = e => e.target.result.createObjectStore('pending_visits', { keyPath: 'id', autoIncrement: true });
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}
