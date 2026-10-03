/**
 * Pending akce navržené AI (WRITE tooly čekající na potvrzení).
 *
 * Tvar odpovídá backendu (backend/ai.py `_run_tool_calls` → `/chat` → `pending_actions[]`):
 *   { "id": "<pending id>", "tool": "...", "arguments": {...}, "expires_at": "..." | null }
 * Potvrzení: POST /actions/confirm  { "action_id": <id> }   (main.ConfirmActionRequest)
 * Zamítnutí: POST /ai/reject/{id}
 *
 * Modul je bez závislostí (testuje se přímo přes `node --test`, viz pendingActions.test.mjs).
 */
export interface PendingAction {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  expires_at?: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Převezme `pending_actions` z API odpovědi a ověří tvar. Položky bez použitelného `id`
 * se vynechají – nešly by potvrdit ani zamítnout (backend by vrátil 422 / 404).
 */
export function normalizePendingActions(raw: unknown): PendingAction[] {
  if (!Array.isArray(raw)) return [];
  const result: PendingAction[] = [];
  for (const item of raw) {
    if (!isRecord(item)) continue;
    const id = item.id;
    if ((typeof id !== "string" && typeof id !== "number") || String(id).trim() === "") continue;
    if (typeof item.tool !== "string") continue;
    result.push({
      id: String(id),
      tool: item.tool,
      arguments: isRecord(item.arguments) ? item.arguments : {},
      expires_at: typeof item.expires_at === "string" ? item.expires_at : null,
    });
  }
  return result;
}

/** Tělo požadavku POST /actions/confirm (backend vyžaduje `action_id`). */
export function confirmActionBody(action: PendingAction): { action_id: string } {
  if (!action.id) throw new Error("Pending akce nemá id – nelze ji potvrdit.");
  return { action_id: action.id };
}

/** Cesta pro POST zamítnutí stejné pending akce (stejné id jako u potvrzení). */
export function rejectActionPath(action: PendingAction): string {
  if (!action.id) throw new Error("Pending akce nemá id – nelze ji zamítnout.");
  return `/ai/reject/${encodeURIComponent(action.id)}`;
}
