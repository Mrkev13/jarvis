export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export function apiUrl(path: string) {
  return `${API_URL}${path}`;
}

/**
 * fetch na backend API, vždy se session cookie (BE vynucuje auth na všech
 * routách mimo login/logout/validate). Při 401 (session vypršela uprostřed
 * práce na stránce – middleware to nezachytí) přesměruje na /login.
 * Response se vrací volajícímu beze změny, ať si stav dořeší sám.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(apiUrl(path), { ...init, credentials: "include" });
  if (res.status === 401) {
    redirectToLogin();
  }
  return res;
}

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (pathname === "/login") return;
  const next = encodeURIComponent(`${pathname}${search}`);
  // Záměrně full reload: apiFetch je utilita mimo React (bez useRouter) a po ztrátě
  // session chceme zahodit i klientský stav stránky.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?next=${next}`);
}

/** Chyba HTTP odpovědi s českým popisem pro uživatele (detail ze serveru, pokud je). */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Text chyby z odpovědi: FastAPI `detail` (řetězec nebo seznam validací), jinak „HTTP 500". */
export async function readErrorDetail(res: Response): Promise<string> {
  if (res.status === 401) return "Přihlášení vypršelo – přihlas se znovu.";
  try {
    const body = (await res.json()) as { detail?: unknown };
    const d = body?.detail;
    if (typeof d === "string" && d.trim()) return d;
    if (Array.isArray(d) && d.length) {
      const first = d[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
  } catch {
    // ne-JSON tělo (HTML chybová stránka, proxy) – níže obecná hláška
  }
  return `Server odpověděl chybou (HTTP ${res.status}).`;
}

/** apiFetch + kontrola res.ok + JSON. Chyba → ApiError s detailem. 204 → null. */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) throw new ApiError(res.status, await readErrorDetail(res));
  if (res.status === 204) return null as T;
  return (await res.json()) as T;
}

/** JSON tělo pro POST/PATCH. */
export function jsonBody(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: string }).name === "AbortError";
}

/** Hláška pro uživatele z libovolné chyby (síť, ApiError…). */
export function errorMessage(error: unknown, fallback = "Nepodařilo se spojit se serverem."): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof TypeError) return fallback; // fetch: síť / CORS / backend neběží
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}
