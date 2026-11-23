/**
 * WoW (MRK-127) – čisté pomocné funkce stránky (testy: lib.test.mjs). Data = snapshot z backendu `GET /wow`.
 */
export type WowProfession = { name: string; skill: number | null; max: number | null; secondary?: boolean };

export type WowCharacter = {
  id: number;
  name: string;
  realm_slug: string;
  realm_name: string;
  level: number | null;
  target_level: number | null;
  levels_to_go: number | null;
  at_target: boolean;
  class_name: string | null;
  race_name: string | null;
  faction: string | null;
  active_spec: string | null;
  item_level: number | null;
  professions: WowProfession[];
  last_login_at: string | null;
  sync_status: "pending" | "ok" | "not_found" | "error";
  sync_label: string;
  last_synced_at: string | null;
};

export type WowOverview = {
  config: { configured: boolean; region: string | null; namespace: string | null };
  summary: { characters: number; max_level: number; with_target: number; at_target: number };
  characters: WowCharacter[];
};

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

/** Postup k cílovému levelu v % (0–100); bez cíle nebo levelu null. */
export function targetProgress(c: Pick<WowCharacter, "level" | "target_level">): number | null {
  if (c.level == null || c.target_level == null || c.target_level <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((c.level / c.target_level) * 100)));
}

/** „Level 42 / 60 · zbývá 18" – text vedle progress baru. */
export function levelLabel(c: Pick<WowCharacter, "level" | "target_level" | "levels_to_go" | "at_target">): string {
  if (c.level == null) return "Level zatím neznámý";
  if (c.target_level == null) return `Level ${c.level}`;
  if (c.at_target) return `Level ${c.level} / ${c.target_level} · cíl splněn`;
  const left = c.levels_to_go ?? Math.max(0, c.target_level - c.level);
  return `Level ${c.level} / ${c.target_level} · zbývá ${left}`;
}

export function syncTone(status: WowCharacter["sync_status"]): Tone {
  return status === "ok" ? "success" : status === "pending" ? "info" : status === "not_found" ? "danger" : "warning";
}

/** „Mining 150/300", u profese bez čísel jen název. */
export function professionLabel(p: WowProfession): string {
  if (p.skill == null) return p.name;
  return p.max != null ? `${p.name} ${p.skill}/${p.max}` : `${p.name} ${p.skill}`;
}

/** „před 3 h" / „před 2 dny" / „právě teď" – kdy byla postava naposledy načtená. */
export function syncedAgo(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "ještě nenačteno";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "ještě nenačteno";
  const min = Math.max(0, Math.round((now.getTime() - t) / 60000));
  if (min < 2) return "právě teď";
  if (min < 60) return `před ${min} min`;
  const h = Math.round(min / 60);
  if (h < 24) return `před ${h} h`;
  const d = Math.round(h / 24);
  return d === 1 ? "včera" : `před ${d} dny`;
}

/** Kontrola formuláře před odesláním (backend kontroluje znovu). Vrací chybu česky nebo null. */
export function validateCharacterForm(name: string, realm: string, target: string): string | null {
  if (!/^\p{L}{2,12}$/u.test(name.trim())) return "Jméno postavy: 2–12 písmen, bez mezer a číslic.";
  if (!realm.trim()) return "Vyplň realm (název serveru).";
  if (target.trim()) {
    const n = Number(target);
    if (!Number.isInteger(n) || n < 1 || n > 100) return "Cílový level: 1–100.";
  }
  return null;
}

/** Výsledek `POST /wow/refresh` (service.sync_due). */
export type WowBatchResult = {
  synced: number;
  results?: Record<string, number>;
  due?: number;
  remaining?: number;
  skipped?: string;
};

const BATCH_ERRORS: Record<string, string> = {
  not_found: "nenalezeno",
  unauthorized: "API odmítlo klíče",
  rate_limited: "API omezuje požadavky",
  unavailable: "API neodpovídá",
  invalid_response: "nečekaná odpověď API",
};

/** Hláška po „Obnovit vše" – úspěch jen když se opravdu něco načetlo; chyby a zbytek nad limit dávky. */
export function batchMessage(r: WowBatchResult): { tone: "success" | "warning"; text: string } {
  if (r.skipped === "not_configured") return { tone: "warning", text: "WoW API není na serveru nastavené – nic se nenačetlo." };
  const failures = Object.entries(r.results ?? {}).filter(([code, n]) => code !== "ok" && n > 0);
  const parts: string[] = [];
  parts.push(r.synced > 0 ? `Aktualizováno: ${r.synced}` : "Nic se neaktualizovalo");
  if (failures.length) parts.push(`selhalo: ${failures.map(([code, n]) => `${n}× ${BATCH_ERRORS[code] ?? code}`).join(", ")}`);
  if (r.remaining && r.remaining > 0) parts.push(`zbývá ${r.remaining} (další se načtou při příští obnově)`);
  return { tone: r.synced > 0 && !failures.length ? "success" : "warning", text: `${parts.join(" · ")}.` };
}
