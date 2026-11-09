/**
 * Web Push (Roadmap 3.0 Phase E) – čisté pomocné funkce bez závislostí (testy: push.test.mjs).
 *
 * Prohlížeč smí Web Push jen v zabezpečeném kontextu (HTTPS nebo localhost). Na iPhonu/iPadu jen v aplikaci
 * přidané na plochu (iOS 16.4+). Oprávnění se nikdy nežádá samo – jen po kliknutí uživatele.
 */
export type PushSupport =
  | { supported: true }
  | { supported: false; reason: "insecure" | "ios_needs_install" | "no_service_worker" | "no_push" | "no_notifications" };

export interface PushEnv {
  isSecureContext: boolean;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  userAgent: string;
  standalone: boolean;
}

export function detectPushSupport(env: PushEnv): PushSupport {
  if (!env.isSecureContext) return { supported: false, reason: "insecure" };
  const ios = /iPhone|iPad|iPod/i.test(env.userAgent);
  if (ios && !env.standalone && !env.hasPushManager) return { supported: false, reason: "ios_needs_install" };
  if (!env.hasServiceWorker) return { supported: false, reason: "no_service_worker" };
  if (!env.hasPushManager) return { supported: false, reason: "no_push" };
  if (!env.hasNotification) return { supported: false, reason: "no_notifications" };
  return { supported: true };
}

/** Prostředí aktuálního prohlížeče (jen na klientu). */
export function currentPushEnv(): PushEnv {
  const nav = navigator as Navigator & { standalone?: boolean };
  return {
    isSecureContext: window.isSecureContext,
    hasServiceWorker: "serviceWorker" in navigator,
    hasPushManager: "PushManager" in window,
    hasNotification: "Notification" in window,
    userAgent: navigator.userAgent,
    standalone: Boolean(nav.standalone) || window.matchMedia?.("(display-mode: standalone)").matches === true,
  };
}

export const UNSUPPORTED_TEXT: Record<Exclude<PushSupport, { supported: true }>["reason"], string> = {
  insecure:
    "Upozornění mimo aplikaci vyžadují HTTPS (např. Tailscale Serve) nebo otevření přes localhost. " +
    "Přes http://100.x.x.x je prohlížeč nepovolí.",
  ios_needs_install:
    "Na iPhonu/iPadu fungují jen v aplikaci přidané na plochu: Sdílet → Přidat na plochu, pak otevřít odtud (iOS 16.4+).",
  no_service_worker: "Tento prohlížeč nepodporuje service workery.",
  no_push: "Tento prohlížeč nepodporuje Web Push.",
  no_notifications: "Tento prohlížeč nepodporuje systémová upozornění.",
};

export const SERVER_REASON_TEXT: Record<string, string> = {
  disabled: "Externí doručení je na serveru vypnuté (EXTERNAL_DELIVERY_ENABLED=false).",
  not_configured: "Server nemá VAPID klíče – spusť backend/scripts/generate_vapid_keys.py a doplň backend/.env.",
  invalid_keys: "VAPID klíče na serveru jsou neplatné.",
  key_mismatch: "Veřejný a privátní VAPID klíč na serveru k sobě nepatří.",
};

/** VAPID veřejný klíč (base64url) → applicationServerKey. */
export function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/**
 * MRK-102: patří odběr ke klíči, který má server teď? `subscriptionKey` = `PushSubscription.options.applicationServerKey`.
 * Po přesunu serveru s novými VAPID klíči telefon drží starý odběr a push služba každou zprávu odmítne (403).
 * `null` = prohlížeč klíč neprozradí (nejde poznat) – pak rozhoduje server (409 stale_key) a výsledek testu.
 */
export function serverKeyMatches(subscriptionKey: ArrayBuffer | null | undefined, publicKey: string): boolean | null {
  if (!subscriptionKey) return null;
  const current = urlBase64ToUint8Array(publicKey);
  const used = new Uint8Array(subscriptionKey);
  if (used.length !== current.length) return false;
  return used.every((byte, i) => byte === current[i]);
}

/** PushSubscription.toJSON() → tělo POST /push/subscriptions (jen endpoint + klíče). */
export function subscriptionBody(json: unknown): { endpoint: string; keys: { p256dh: string; auth: string } } {
  const j = json as { endpoint?: unknown; keys?: { p256dh?: unknown; auth?: unknown } } | null;
  const endpoint = typeof j?.endpoint === "string" ? j.endpoint : "";
  const p256dh = typeof j?.keys?.p256dh === "string" ? j.keys.p256dh : "";
  const auth = typeof j?.keys?.auth === "string" ? j.keys.auth : "";
  if (!endpoint.startsWith("https://") || !p256dh || !auth) throw new Error("Prohlížeč vrátil neúplný odběr.");
  return { endpoint, keys: { p256dh, auth } };
}

export type DeviceState = "checking" | "unsupported" | "server_off" | "denied" | "off" | "on" | "stale";

/** MRK-102: vysvětlení stavu „stale" (odběr ke starým klíčům serveru). */
export const STALE_TEXT =
  "Server má od posledního připojení jiné klíče pro upozornění (např. po přesunu na jiný počítač). " +
  "Starý odběr už nefunguje – klepni na „Znovu připojit“.";

/** Výsledek „Poslat test" → věta pro člověka; `stale` = odběr je potřeba připojit znovu. */
export function testResultText(ok: boolean, error: string | null | undefined): { text: string; stale: boolean } {
  if (ok) return { text: "Test odeslán – upozornění by mělo za chvíli přijít.", stale: false };
  switch (error) {
    case "http_401":
    case "http_403":
    case "http_404":
    case "http_410":
    case "not_subscribed":
      return { text: "Push služba tento odběr odmítla. " + STALE_TEXT, stale: true };
    case "not_configured":
      return { text: "Server nemá nastavené klíče pro upozornění.", stale: false };
    default:
      return { text: `Test se nepodařilo doručit (${error ?? "neznámá chyba"}). Zkus to za chvíli znovu.`, stale: false };
  }
}

export function deviceStateLabel(state: DeviceState): string {
  switch (state) {
    case "on":
      return "Připojeno – připomínky přijdou i mimo aplikaci";
    case "stale":
      return "Je potřeba se znovu připojit";
    case "off":
      return "Nepřipojeno";
    case "denied":
      return "Upozornění jsou v prohlížeči zakázaná";
    case "server_off":
      return "Server externí doručení nemá zapnuté";
    case "unsupported":
      return "Na tomto zařízení nejde zapnout";
    default:
      return "Zjišťuji…";
  }
}
