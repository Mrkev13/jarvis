/**
 * Denní přehled (Roadmap 3.0 Phase F) – čisté pomocné funkce pro kartu na dashboardu.
 *
 * Backend (`GET /briefing/today`) vrací jeden přehled na pražský den; obsah je už „uzemněný" na reálná data
 * (každá položka má `ref` + odkaz `url`). Tady se jen rozhoduje, jaký stav ukázat a jak.
 * Modul je bez závislostí (testuje se přes `node --test`, viz briefing.test.mjs).
 */
export type BriefingItem = {
  ref: string;
  kind: string;
  text: string;
  label: string;
  when: string;
  url: string;
  detail: string;
  new: boolean;
  why?: string;
};

export type BriefingContent = {
  summary: string;
  priorities: BriefingItem[];
  watch: BriefingItem[];
  upcoming: BriefingItem[];
  note: string | null;
  quiet?: boolean;
  date?: string;
};

export type FallbackItem = { ref: string; kind: string; label: string; when: string; url: string; detail: string };

export type BriefingPayload = {
  date: string;
  enabled: boolean;
  scheduled_time: string;
  status: "missing" | "generating" | "ready" | "failed" | string;
  briefing: BriefingContent | null;
  generated_at: string | null;
  generated_label: string | null;
  trigger: string | null;
  regenerated_count: number;
  error_category: string | null;
  error_text: string | null;
  fallback: { today?: FallbackItem[]; overdue?: FallbackItem[]; soon?: FallbackItem[] } | null;
};

export type BriefingView =
  | { kind: "ready"; content: BriefingContent; warning: string | null }
  | { kind: "generating" }
  | { kind: "failed"; message: string }
  | { kind: "scheduled"; message: string }
  | { kind: "missing"; message: string }
  | { kind: "disabled"; message: string };

const PRAGUE_TZ = "Europe/Prague";

/** Pražský čas „HH:MM" pro daný okamžik (nezávisle na pásmu prohlížeče). */
export function pragueHHMM(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: PRAGUE_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
  return `${get("hour")}:${get("minute")}`;
}

/** Který stav karty ukázat. */
export function briefingView(p: BriefingPayload, now: Date = new Date()): BriefingView {
  if (p.briefing) {
    const warning = p.error_category?.startsWith("regenerate_failed")
      ? `Přegenerování se nepovedlo – zůstává předchozí verze. ${p.error_text ?? ""}`.trim()
      : null;
    return { kind: "ready", content: p.briefing, warning };
  }
  if (p.status === "generating") return { kind: "generating" };
  if (p.status === "failed") {
    return { kind: "failed", message: p.error_text ?? "Přehled se nepodařilo vytvořit." };
  }
  if (!p.enabled) {
    return { kind: "disabled", message: "Automatický přehled je vypnutý – můžeš ho vytvořit ručně." };
  }
  if (pragueHHMM(now) < p.scheduled_time) {
    return { kind: "scheduled", message: `Přehled se vytvoří automaticky v ${p.scheduled_time}.` };
  }
  return { kind: "missing", message: "Dnešní přehled zatím není hotový." };
}

/** Tlačítko: první vytvoření, nebo přegenerování (to vyžaduje potvrzení). */
export function generateAction(p: BriefingPayload | null): { label: string; regenerate: boolean } | null {
  if (!p || p.status === "generating") return null;
  return p.briefing ? { label: "Přegenerovat", regenerate: true } : { label: "Vytvořit přehled", regenerate: false };
}

/** Jen interní odkazy (z dat aplikace); cokoliv jiného → bez odkazu. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url || !url.startsWith("/") || url.startsWith("//")) return null;
  return url;
}

/** Popisek „Vytvořeno v 07:00 · přegenerováno 1×". */
export function generatedCaption(p: BriefingPayload): string | null {
  if (!p.generated_label) return null;
  const how = p.trigger === "manual" ? "ručně" : p.trigger === "catchup" ? "dodatečně" : null;
  const parts = [`Vytvořeno v ${p.generated_label}${how ? ` (${how})` : ""}`];
  if (p.regenerated_count > 0) parts.push(`přegenerováno ${p.regenerated_count}×`);
  return parts.join(" · ");
}

/** Deterministický náhled, když AI přehled není (žádné LLM, jen reálná data). */
export function fallbackGroups(p: BriefingPayload): { title: string; items: FallbackItem[] }[] {
  const f = p.fallback;
  if (!f) return [];
  return [
    { title: "Po termínu / nevyřízené", items: f.overdue ?? [] },
    { title: "Dnes", items: f.today ?? [] },
    { title: "Brzy", items: f.soon ?? [] },
  ].filter((g) => g.items.length > 0);
}

