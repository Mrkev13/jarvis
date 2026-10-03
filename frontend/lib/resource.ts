/**
 * Stav načítání dat ze serveru (Roadmap 4A) – čistý reducer pro hooks/useApiResource.ts.
 *
 * - Na začátku `loading` (žádné „nic tu není" před prvním načtením).
 * - Obnovení se starými daty = `refreshing` (žádný skeleton, žádné blikání).
 * - Odpovědi starších požadavků se zahodí (requestId) – rychlé psaní ve filtru nevrátí staré výsledky.
 * Testy: resource.test.mjs.
 */
export type ResourceStatus = "idle" | "loading" | "success" | "error";

export type ResourceState<T> = {
  status: ResourceStatus;
  data: T | null;
  error: string | null;
  refreshing: boolean;
  requestId: number;
};

export type ResourceAction<T> =
  | { type: "start"; id: number }
  | { type: "success"; id: number; data: T }
  | { type: "error"; id: number; error: string }
  | { type: "set"; data: T }
  | { type: "idle" };

export function initialResource<T>(enabled = true): ResourceState<T> {
  return { status: enabled ? "loading" : "idle", data: null, error: null, refreshing: false, requestId: 0 };
}

export function resourceReducer<T>(state: ResourceState<T>, action: ResourceAction<T>): ResourceState<T> {
  switch (action.type) {
    case "start": {
      const hasData = state.data !== null;
      return {
        ...state,
        status: hasData ? state.status : "loading",
        refreshing: hasData,
        requestId: action.id,
      };
    }
    case "success":
      if (action.id !== state.requestId) return state; // zastaralá odpověď
      return { status: "success", data: action.data, error: null, refreshing: false, requestId: state.requestId };
    case "error":
      if (action.id !== state.requestId) return state;
      // Při chybě obnovení si necháme poslední data (stránka nezmizí), ale chybu ukážeme.
      return { ...state, status: state.data !== null ? "success" : "error", error: action.error, refreshing: false };
    case "set":
      return { ...state, status: "success", data: action.data, error: null };
    case "idle":
      return { ...initialResource<T>(false), requestId: state.requestId };
    default:
      return state;
  }
}
