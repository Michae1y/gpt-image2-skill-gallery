const CACHE_PREFIX = 'gpt-image2-gallery';
const APP_CACHE = `${CACHE_PREFIX}-app-v1`;
const IMAGE_CACHE = `${CACHE_PREFIX}-images-v1`;
const APP_ASSETS = ['./', './index.html', './assets/styles.css'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(APP_CACHE)
      .then((cache) => cache.addAll(APP_ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((key) => {
        if (key.startsWith(CACHE_PREFIX) && key !== APP_CACHE && key !== IMAGE_CACHE) {
          return caches.delete(key);
        }
        return undefined;
      })))
      .then(() => self.clients.claim())
  );
});

const isSameOrigin = (request) => new URL(request.url).origin === self.location.origin;

const networkFirst = async (request) => {
  const cache = await caches.open(APP_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    throw error;
  }
};

const cacheFirstImage = async (request) => {
  const cache = await caches.open(IMAGE_CACHE);
  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }

  const response = await fetch(request);
  if (response.ok) {
    cache.put(request, response.clone());
  }
  return response;
};

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET' || !isSameOrigin(request)) {
    return;
  }

  const url = new URL(request.url);
  if (url.pathname.includes('/assets/images/') || url.pathname.includes('/assets/full/')) {
    event.respondWith(cacheFirstImage(request));
    return;
  }

  if (request.mode === 'navigate' || url.pathname.endsWith('/index.html') || url.pathname.endsWith('/assets/styles.css')) {
    event.respondWith(networkFirst(request));
  }
});
