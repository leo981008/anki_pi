// Service Worker for Offline Swipe Mode
const CACHE_NAME = 'ankipi-swipe-v1';
const ASSETS_TO_CACHE = [
    '/static/manifest.json',
    '/static/icon-192.png',
    '/static/icon-512.png',
    '/static/js/idb.js'
    // Note: swipe_mode.html is dynamic (contains deck_id), so we cache it dynamically or rely on network-first
];

self.addEventListener('install', (event) => {
    console.log('[Service Worker] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Service Worker] Caching app shell');
            return cache.addAll(ASSETS_TO_CACHE);
        })
    );
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    console.log('[Service Worker] Activating...');
    event.waitUntil(
        caches.keys().then((keyList) => {
            return Promise.all(keyList.map((key) => {
                if (key !== CACHE_NAME) {
                    console.log('[Service Worker] Removing old cache', key);
                    return caches.delete(key);
                }
            }));
        })
    );
    return self.clients.claim();
});

// Fetch Strategy: Network First, falling back to Cache
// This ensures we get the latest HTML/JS if online, but can still load if offline
self.addEventListener('fetch', (event) => {
    // Only handle GET requests
    if (event.request.method !== 'GET') return;

    // Skip API calls (handled by application logic / IndexedDB) unless it's the TTS cache
    // Actually, TTS calls will be cached by the application in IndexedDB, so SW doesn't need to cache /api/
    // except maybe for the static assets and the HTML page itself.

    if (event.request.url.includes('/api/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                // If network fetch succeeds, clone and cache it (if it's a valid response)
                if (!response || response.status !== 200 || response.type !== 'basic') {
                    return response;
                }
                const responseToCache = response.clone();
                caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, responseToCache);
                });
                return response;
            })
            .catch(() => {
                // Network failed, try cache
                return caches.match(event.request);
            })
    );
});
