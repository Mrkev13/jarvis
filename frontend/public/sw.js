/* Standa Hub service worker – jen Web Push (Roadmap 3.0 Phase E). Žádné cachování ani offline režim.
   Zprávu šifruje backend (RFC 8291); obsah: { title, body, url, tag }. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "Standa Hub", body: event.data ? event.data.text() : "" };
  }
  const title = typeof data.title === "string" && data.title ? data.title : "Standa Hub";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: typeof data.body === "string" ? data.body : "",
      tag: typeof data.tag === "string" ? data.tag : undefined,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: typeof data.url === "string" ? data.url : "/reminders" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Jen cesty v rámci aplikace – nikdy cizí URL z obsahu zprávy.
  const raw = event.notification.data && event.notification.data.url;
  const path = typeof raw === "string" && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/reminders";
  const target = new URL(path, self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.startsWith(self.location.origin) && "focus" in client) {
          client.navigate(target).catch(() => undefined);
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
