/**
 * Sémantika vzhledu (Roadmap 4A): tóny → třídy, mapování stavů na tóny, české popisky.
 * Čisté funkce bez Reactu (testy: ui.test.mjs). Celé názvy tříd jsou zde doslova, aby je Tailwind našel.
 */
export type Tone = "neutral" | "accent" | "ai" | "success" | "warning" | "danger" | "info";

/** Spojí třídy; vynechá prázdné hodnoty. */
export function cx(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}

export const BADGE_TONE: Record<Tone, string> = {
  neutral: "border-line bg-surface-2 text-ink-2",
  accent: "border-accent/40 bg-accent/10 text-accent-strong",
  ai: "border-accent-2/40 bg-accent-2/10 text-accent-2",
  success: "border-success/35 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
  info: "border-info/35 bg-info/10 text-info",
};

export const TEXT_TONE: Record<Tone, string> = {
  neutral: "text-ink-2",
  accent: "text-accent-strong",
  ai: "text-accent-2",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
};

export const BAR_TONE: Record<Tone, string> = {
  neutral: "bg-neutral",
  accent: "bg-accent",
  ai: "bg-accent-2",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
};

/** Okraj/plocha karty podle tónu (jen pro karty, které opravdu něco hlásí). */
export const CARD_TONE: Record<Tone, string> = {
  neutral: "border-line bg-surface",
  accent: "border-accent/30 bg-surface",
  ai: "border-accent-2/30 bg-surface",
  success: "border-success/30 bg-success/[0.04]",
  warning: "border-warning/40 bg-warning/[0.06]",
  danger: "border-danger/40 bg-danger/[0.06]",
  info: "border-info/30 bg-surface",
};

export function clampPercent(value: unknown): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Závažnost notifikace (important / warning / info) → tón + český popisek. */
export function severityTone(severity: string | null | undefined): { tone: Tone; label: string } {
  const s = String(severity || "info").toLowerCase();
  if (s === "important") return { tone: "danger", label: "Důležité" };
  if (s === "warning") return { tone: "warning", label: "Varování" };
  return { tone: "info", label: "Info" };
}

/** Priorita (high / medium / low) → tón + český popisek. Vysoká je jediná zvýrazněná. */
export function priorityTone(priority: string | null | undefined): { tone: Tone; label: string } {
  const p = String(priority || "medium").toLowerCase();
  if (p === "high") return { tone: "warning", label: "Vysoká" };
  if (p === "low") return { tone: "neutral", label: "Nízká" };
  return { tone: "neutral", label: "Střední" };
}

/** Trend metriky z backendu (better/worse/…) → tón; polaritu určuje backend, ne UI. */
export function trendTone(trend: string | null | undefined): Tone {
  if (trend === "better") return "success";
  if (trend === "worse") return "danger";
  return "neutral";
}

/** Barva progress baru: neutrálně akcent; „hotovo" zeleně; sémantika jen pokud ji volající dá. */
export function progressTone(percent: number, tone?: Tone): Tone {
  if (tone) return tone;
  return clampPercent(percent) >= 100 ? "success" : "accent";
}
