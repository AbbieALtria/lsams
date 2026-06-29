const CACHE = 'lsams-v4';
const OFFLINE_PAGE = '/gabay/offline';

// All gabay pages pre-cached on install so offline works immediately after first visit
const PRECACHE = [
  '/gabay/app',
  '/gabay/app/leads',
  '/gabay/app/leads-json',
  '/gabay/app/checkin',
  '/gabay/app/visits',
  '/gabay/app/profile',
  '/gabay/app/route',
  '/gabay/app/tutorial',
  '/gabay/offline',
  '/static/icons/icon-192.png',
  '/static/gabay/i18n.js',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js',
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(cache => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
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

  // Leads JSON — stale-while-revalidate (offline: serve cached, update in bg)
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

  // App pages — network first, fall back to cache, then offline page
  if (e.request.url.includes(self.location.origin)) {
    e.respondWith(
      fetch(e.request)
        .then(res => {
          // Only cache successful HTML responses
          if (res.ok && res.type !== 'opaque') {
            const clone = res.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return res;
        })
        .catch(() =>
          caches.match(e.request)
            .then(cached => cached || caches.match(OFFLINE_PAGE))
        )
    );
  }
});

// ── Background Sync ───────────────────────────────────────────────────────────
self.addEventListener('sync', e => {
  if (e.tag === 'sync-visits') {
    e.waitUntil(syncPendingVisits());
  }
});

async function syncPendingVisits() {
  const db = await openDB();
  const all = await getAllRecords(db);
  if (!all.length) return;

  let synced = 0;
  for (const record of all) {
    try {
      const fd = new FormData();

      // Text fields
      const data = record.data || {};
      for (const [k, v] of Object.entries(data)) {
        if (v != null && v !== '') fd.append(k, v);
      }

      // Photos stored as ArrayBuffer → restore to Blob
      if (record.photo_selfie) {
        fd.append('photo_selfie',
          new Blob([record.photo_selfie], { type: record.photo_selfie_type || 'image/jpeg' }),
          'selfie.jpg');
      }
      if (record.photo_proof) {
        fd.append('photo_proof',
          new Blob([record.photo_proof], { type: record.photo_proof_type || 'image/jpeg' }),
          'proof.jpg');
      }

      const res = await fetch('/api/gabay/sync', { method: 'POST', body: fd });
      const json = await res.json().catch(() => ({}));

      if (json.ok) {
        await deleteRecord(db, record.id);
        synced++;
      }
    } catch (_) {
      // Will retry on next sync event
    }
  }

  if (synced > 0) {
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => c.postMessage({ type: 'sync_complete', count: synced }));
  }
}

// ── Push Notifications ────────────────────────────────────────────────────────
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

// ── IndexedDB helpers ─────────────────────────────────────────────────────────
function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('lsams', 1);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains('pending_visits')) {
        db.createObjectStore('pending_visits', { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}

function getAllRecords(db) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pending_visits', 'readonly');
    const req = tx.objectStore('pending_visits').getAll();
    req.onsuccess = e => resolve(e.target.result);
    req.onerror = reject;
  });
}

function deleteRecord(db, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('pending_visits', 'readwrite');
    const req = tx.objectStore('pending_visits').delete(id);
    req.onsuccess = resolve;
    req.onerror = reject;
  });
}
