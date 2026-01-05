// ScreenShare Pro Service Worker
const CACHE_NAME = "screenshare-pro-v1";
const STATIC_ASSETS = [
  "/",
  "/login",
  "/register",
  "/dashboard",
  "/static/js/auth.js",
  "/static/js/webrtc.js",
  "/static/css/output.css",
  "/static/icons/icon-192x192.png",
  "/static/icons/icon-512x512.png",
  "/static/manifest.json",
];

// Install event - cache static assets
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log("Caching static assets");
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate event - clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  self.clients.claim();
});

// Fetch event - network first, fallback to cache
self.addEventListener("fetch", (event) => {
  // Skip WebSocket requests
  if (event.request.url.includes("/ws/")) {
    return;
  }

  // Skip API requests - always fetch from network
  if (event.request.url.includes("/api/")) {
    event.respondWith(fetch(event.request));
    return;
  }

  // For other requests - network first, cache fallback
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Clone response for caching
        if (response.status === 200) {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // Fallback to cache
        return caches.match(event.request).then((cachedResponse) => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // Return offline page for navigation requests
          if (event.request.mode === "navigate") {
            return caches.match("/");
          }
          return new Response("Offline", { status: 503 });
        });
      })
  );
});

// Push notification support
self.addEventListener("push", (event) => {
  if (event.data) {
    const data = event.data.json();
    const options = {
      body: data.body || "Yeni bildirim",
      icon: "/static/icons/icon-192x192.png",
      badge: "/static/icons/icon-72x72.png",
      vibrate: [100, 50, 100],
      data: {
        url: data.url || "/",
      },
    };
    event.waitUntil(
      self.registration.showNotification(
        data.title || "ScreenShare Pro",
        options
      )
    );
  }
});

// Notification click
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url));
});
