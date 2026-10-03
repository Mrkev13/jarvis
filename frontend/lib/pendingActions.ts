/**
 * Pending akce navržené AI (WRITE tooly čekající na potvrzení).
 *
 * Tvar odpovídá backendu (backend/ai.py `_run_tool_calls` → `/chat` → `pending_actions[]`):
 *   { "id": "<pending id>", "tool": "...", "arguments": {...}, "expires_at": "..." | null }
 * Potvrzení: POST /actions/confirm  { "action_id": <id> }   (main.ConfirmActionRequest)
 * Zamítnutí: POST /ai/reject/{id}
 *
 * Úpravy / mazání / dokončení (Roadmap 3.0 Phase B, tool `modify_records`) nesou navíc `preview`,
 * který backend sestavil z ověřených dat: co se změní (staré → nové), u dávky počet záznamů.
 * Karta se z něj vykreslí obecně – bez zvláštního UI pro každý modul.
 *
 * Modul je bez závislostí (testuje se přímo přes `node --test`, viz pendingActions.test.mjs).
 */
export interface PreviewChange {
  label: string;
  old: string;
  new: string;
}

export interface PreviewItem {
  label: string;
  changes: PreviewChange[];
}

export interface PendingPreview {
  kind: "update" | "delete" | "complete" | string;
  title: string;
  count: number;
  items: PreviewItem[];
  warnings: string[];
}

export interface PendingAction {
  id: string;
  tool: string;
  arguments: Record<string, unknown>;
  expires_at?: string | null;
  preview?: PendingPreview | null;
}

export interface ActionCardInfo {
  title: string;
  fields: { label: string; value: string }[];
  footer: { label: string; value: string } | null;
  detailLines: string[];
}

const MAX_PREVIEW_ITEMS = 10;

function str(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

/** Bezpečně převezme preview z backendu (položka `preview`, nebo uložený plán `arguments.plan.preview`). */
export function normalizePreview(raw: unknown, args?: Record<string, unknown>): PendingPreview | null {
  let candidate = raw;
  if (!isRecord(candidate) && args && isRecord(args.plan)) {
    candidate = args.plan.preview;
  }
  if (!isRecord(candidate) || typeof candidate.title !== "string" || !Array.isArray(candidate.items)) {
    return null;
  }
  const items: PreviewItem[] = candidate.items.filter(isRecord).map((item) => ({
    label: str(item.label),
    changes: Array.isArray(item.changes)
      ? item.changes.filter(isRecord).map((c) => ({ label: str(c.label), old: str(c.old), new: str(c.new) }))
      : [],
  }));
  const count = Number(candidate.count);
  return {
    kind: str(candidate.kind),
    title: candidate.title,
    count: Number.isFinite(count) && count > 0 ? count : items.length,
    items,
    warnings: Array.isArray(candidate.warnings) ? candidate.warnings.map(str).filter(Boolean) : [],
  };
}

/** Obecná karta pro úpravu / smazání / dokončení: cíl, staré → nové, u dávky počet a seznam. */
export function describePreview(preview: PendingPreview): ActionCardInfo {
  const fields: { label: string; value: string }[] = [];
  const actionLabel =
    preview.kind === "delete"
      ? "Smazání"
      : preview.kind === "complete"
        ? "Označit jako hotové"
        : preview.kind === "undo"
          ? "Vrácení změny"
          : "Úprava";
  fields.push({ label: "Akce", value: actionLabel });
  if (preview.items.length === 1) {
    const [item] = preview.items;
    fields.push({ label: "Záznam", value: item.label });
    for (const c of item.changes) fields.push({ label: c.label, value: `${c.old} → ${c.new}` });
  } else {
    preview.items.slice(0, MAX_PREVIEW_ITEMS).forEach((item, i) => {
      const changes = item.changes.map((c) => `${c.label}: ${c.old} → ${c.new}`).join(", ");
      fields.push({ label: `${i + 1}.`, value: changes ? `${item.label} (${changes})` : item.label });
    });
    if (preview.items.length > MAX_PREVIEW_ITEMS) {
      fields.push({ label: "…", value: `a dalších ${preview.items.length - MAX_PREVIEW_ITEMS}` });
    }
  }
  for (const w of preview.warnings) fields.push({ label: "Upozornění", value: w });
  return {
    title: preview.title,
    fields,
    footer: preview.count > 1 || preview.kind === "delete"
      ? { label: "Počet záznamů", value: String(preview.count) }
      : null,
    detailLines: [
      ...preview.items.slice(0, MAX_PREVIEW_ITEMS).map((i) => i.label),
      ...(preview.count > 1 ? [`Záznamů: ${preview.count}`] : []),
    ],
  };
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
    const args = isRecord(item.arguments) ? item.arguments : {};
    result.push({
      id: String(id),
      tool: item.tool,
      arguments: args,
      expires_at: typeof item.expires_at === "string" ? item.expires_at : null,
      preview: normalizePreview(item.preview, args),
    });
  }
  return result;
}

/** Tělo požadavku POST /actions/confirm (backend vyžaduje `action_id`). */
export function confirmActionBody(action: PendingAction): { action_id: string } {
  if (!action.id) throw new Error("Pending akce nemá id – nelze ji potvrdit.");
  return { action_id: action.id };
}

/** Phase C: POST /actions/undo s id PROVEDENÉ akce → backend vrátí novou undo pending akci k potvrzení. */
export const UNDO_PATH = "/actions/undo";

export function undoActionBody(actionId: string): { action_id: string } {
  if (!actionId) throw new Error("Chybí id provedené akce – nelze ji vrátit.");
  return { action_id: actionId };
}

/** Potvrzená akce jde vrátit, jen když to backend výslovně řekne (result.undo_available === true). */
export function isUndoAvailable(confirmResponse: unknown): boolean {
  if (!isRecord(confirmResponse) || confirmResponse.ok !== true) return false;
  const result = confirmResponse.result;
  return isRecord(result) && result.undo_available === true;
}

/** Cesta pro POST zamítnutí stejné pending akce (stejné id jako u potvrzení). */
export function rejectActionPath(action: PendingAction): string {
  if (!action.id) throw new Error("Pending akce nemá id – nelze ji zamítnout.");
  return `/ai/reject/${encodeURIComponent(action.id)}`;
}
