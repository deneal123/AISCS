// Версия кэша. Обязательно менять при изменении стратегии: `activate` удаляет
// все кэши с другим именем, и это единственный способ вылечить пользователей,
// у которых осел старый кэш.
const CACHE_NAME = 'gpthub-v3';
const OFFLINE_URL = '/index.html';
const PRECACHE_URLS = [OFFLINE_URL, '/favicon-gpthub.svg', '/gpthub-logo.svg'];

// Статика CRA хеширована в имени файла (main.66723d04.js) — cache-first безопасен:
// новая сборка = новое имя = промах кэша.
const isHashedAsset = (url) => url.pathname.startsWith('/static/');

const putInCache = (request, response) => {
  if (!response || response.status !== 200 || response.type !== 'basic') return;
  const clone = response.clone();
  caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
};

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (url.origin !== self.location.origin) return;
  if (request.method !== 'GET') return;

  // API не кэшируем вообще. Ответы приватные (баланс, история операций, профиль)
  // и быстро протухают; раньше они складывались в Cache Storage и переживали
  // выход из аккаунта.
  if (url.pathname.startsWith('/api/')) return;

  // Навигации — network-first. Раньше здесь был cache-first, и вернувшийся
  // пользователь получал старый index.html со ссылками на уже удалённые чанки:
  // новые деплои до него не доезжали НИКОГДА. Кэш — только офлайн-фолбэк.
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          putInCache(OFFLINE_URL, response);
          return response;
        })
        .catch(() => caches.match(OFFLINE_URL))
    );
    return;
  }

  // Хешированная статика — cache-first.
  if (isHashedAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            putInCache(request, response);
            return response;
          })
      )
    );
    return;
  }

  // Остальное (иконки, манифест) — stale-while-revalidate.
  event.respondWith(
    caches.match(request).then((cached) => {
      const fromNetwork = fetch(request)
        .then((response) => {
          putInCache(request, response);
          return response;
        })
        .catch(() => cached);
      return cached || fromNetwork;
    })
  );
});
