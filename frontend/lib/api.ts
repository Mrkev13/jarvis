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
