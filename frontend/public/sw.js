/* Standa Hub service worker – jen Web Push (Roadmap 3.0 Phase E). Žádné cachování ani offline režim.
   Zprávu šifruje backend (RFC 8291); obsah: { title, body, url, tag, kind?, reminder_id? }.
   MRK-80: připomínka (kind "reminder") zůstane viset do odkliknutí, zavibruje, při stejném tagu upozorní znovu
   (renotify) a má akce Hotovo / Odložit 10 min. Adresu API dostane worker v query registrace (/sw.js?api=…),
   protože backend běží na jiném originu než frontend.
   MRK-149: docházka (kind "attendance", subject_id, week_start) má akce Byl / Nebyl → PUT docházky přímo z oznámení. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

const REMINDER_VIBRATE = [200, 100, 200, 100, 200];
const SNOOZE_MINUTES = 10;

/** Origin API z registrace – jen http(s), nic jiného (žádné cesty ani cizí schéma). */
function apiOrigin() {
  try {
    const raw = new URL(self.location.href).searchParams.get("api");
    if (!raw) return null;
    const url = new URL(raw);
    return url.protocol === "https:" || url.protocol === "http:" ? url.origin : null;
  } catch {
    return null;
  }
}

function positiveId(value) {
  return Number.isInteger(value) && value > 0 ? value : null;
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "Standa Hub", body: event.data ? event.data.text() : "" };
  }
  const title = typeof data.title === "string" && data.title ? data.title : "Standa Hub";
  const tag = typeof data.tag === "string" ? data.tag : undefined;
  const reminderId = data.kind === "reminder" ? positiveId(data.reminder_id) : null;
  const attendance = data.kind === "attendance" ? attendanceRef(data.subject_id, data.week_start) : null;
  const options = {
    body: typeof data.body === "string" ? data.body : "",
    tag,
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: typeof data.url === "string" ? data.url : "/reminders", reminderId, attendance },
  };
  if (attendance && apiOrigin()) {
    options.actions = [
      { action: "present", title: "Byl" },
      { action: "absent", title: "Nebyl" },
    ];
  }
  if (reminderId) {
    Object.assign(options, {
      requireInteraction: true,
      renotify: Boolean(tag), // renotify bez tagu prohlížeč odmítne
      vibrate: REMINDER_VIBRATE,
      actions: apiOrigin()
        ? [
            { action: "done", title: "Hotovo" },
            { action: "snooze", title: `Odložit ${SNOOZE_MINUTES} min` },
          ]
        : [],
    });
  }
  event.waitUntil(self.registration.showNotification(title, options));
});

/** Hotovo / Odložit přímo z oznámení (cookie relace, stejné endpointy jako aplikace). */
async function reminderAction(action, reminderId) {
  const api = apiOrigin();
  if (!api) return false;
  const path = action === "done" ? `/reminders/${reminderId}/done` : `/reminders/${reminderId}/snooze`;
  const init = { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" } };
  if (action === "snooze") init.body = JSON.stringify({ minutes: SNOOZE_MINUTES });
  try {
    const res = await fetch(`${api}${path}?source=push`, init);
    return res.ok;
  } catch {
    return false;
  }
}

/** MRK-149: jen kladné id předmětu a datum YYYY-MM-DD – nic jiného z obsahu zprávy se do požadavku nedostane. */
function attendanceRef(subjectId, week) {
  const id = positiveId(subjectId);
  return id && typeof week === "string" && /^\d{4}-\d{2}-\d{2}$/.test(week) ? { subjectId: id, week } : null;
}

/** Byl / Nebyl přímo z oznámení (cookie relace, stejný endpoint jako stránka Škola). */
async function attendanceAction(ref, present) {
  const api = apiOrigin();
  if (!api) return false;
  try {
    const res = await fetch(`${api}/school/subject/${ref.subjectId}/attendance`, {
      method: "PUT",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ week_start: ref.week, present }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

function openApp(path) {
  const target = new URL(path, self.location.origin).href;
  return self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const client of list) {
      if (client.url.startsWith(self.location.origin) && "focus" in client) {
        client.navigate(target).catch(() => undefined);
        return client.focus();
      }
    }
    return self.clients.openWindow(target);
  });
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const data = event.notification.data || {};
  // Jen cesty v rámci aplikace – nikdy cizí URL z obsahu zprávy.
  const raw = data.url;
  const path = typeof raw === "string" && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/reminders";
  const reminderId = positiveId(data.reminderId);
  const attendance = data.attendance ? attendanceRef(data.attendance.subjectId, data.attendance.week) : null;
  if (attendance && (event.action === "present" || event.action === "absent")) {
    event.waitUntil(
      attendanceAction(attendance, event.action === "present").then((ok) =>
        // nepovedlo se (offline, odhlášeno, týden bez výuky…) → otevřít Školu, ať to jde zapsat ručně
        ok ? undefined : openApp(`/school?subject=${attendance.subjectId}`),
      ),
    );
    return;
  }
  if (reminderId && (event.action === "done" || event.action === "snooze")) {
    event.waitUntil(
      reminderAction(event.action, reminderId).then((ok) =>
        // nepovedlo se (offline, odhlášeno…) → otevřít Připomínky, ať to jde udělat ručně
        ok ? undefined : openApp(`/reminders?reminder=${reminderId}`),
      ),
    );
    return;
  }
  event.waitUntil(openApp(path));
});
