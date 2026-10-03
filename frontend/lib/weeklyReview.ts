/**
 * Týdenní přehled (Roadmap 3.0 Phase G) – čisté pomocné funkce pro /review a kartu na dashboardu.
 *
 * Backend vrací jeden přehled na pražský týden (pondělí–neděle). Obsah je oddělený na fakta (wins/concerns),
 * srovnání (metriky spočítané předem), příští týden a odhady (forecasts – s jistotou a podkladem z dat).
 * Interní odkazy (`ref`) se nikdy nezobrazují. Modul je bez závislostí (testy: weeklyReview.test.mjs).
 */
export type MetricView = {
  key: string;
  label: string;
  unit: string;
  cur: number;
  prev: number | null;
  prev_label: string;
  delta: number | null;
  pct: number | null;
  trend: "better" | "worse" | "same" | "up" | "down" | "n/a" | string;
  cur_text: string;
  prev_text: string | null;
  delta_text: string;
  note: string;
};

export type WeeklyItem = {
  ref: string;
  text: string;
  kind: string;
  url: string;
  label?: string;
  when?: string;
  detail?: string;
  metric?: MetricView;
};

export type ForecastView = {
  ref: string;
  statement: string;
  confidence: "high" | "moderate" | "low" | string;
  confidence_text: string;
  rule: string;
  basis_labels: string[];
};

export type WeeklyContent = {
  headline: string;
  summary: string;
  wins: WeeklyItem[];
  concerns: WeeklyItem[];
  comparisons: WeeklyItem[];
  next_week: WeeklyItem[];
  forecasts: ForecastView[];
  focus: WeeklyItem[];
  quiet?: boolean;
  partial?: boolean;
};

export type WeeklyPayload = {
  week_start: string;
  week_label: string;
  is_current: boolean;
  can_generate: boolean;
  enabled: boolean;
  schedule_label: string;
  status: "missing" | "generating" | "ready" | "failed" | string;
  review: WeeklyContent | null;
  generated_label: string | null;
  period_end_label: string | null;
  trigger: string | null;
  regenerated_count: number;
  error_category: string | null;
  error_text: string | null;
  fallback: WeeklyContent | null;
};

export type HistoryItem = { week_start: string; week_label: string; status: string; headline: string | null };

export type ReviewView =
  | { kind: "ready"; content: WeeklyContent; warning: string | null }
  | { kind: "generating" }
  | { kind: "failed"; message: string }
  | { kind: "missing"; message: string }
  | { kind: "disabled"; message: string };

/** Který stav ukázat. */
export function reviewView(p: WeeklyPayload): ReviewView {
  if (p.review) {
    const warning = p.error_category?.startsWith("regenerate_failed")
      ? `Přegenerování se nepovedlo – zůstává předchozí verze. ${p.error_text ?? ""}`.trim()
      : null;
    return { kind: "ready", content: p.review, warning };
  }
  if (p.status === "generating") return { kind: "generating" };
  if (p.status === "failed") return { kind: "failed", message: p.error_text ?? "Přehled se nepodařilo vytvořit." };
  if (!p.enabled) return { kind: "disabled", message: "Automatický týdenní přehled je vypnutý – můžeš ho vytvořit ručně." };
  if (!p.is_current) return { kind: "missing", message: "Pro tento týden přehled není." };
  return { kind: "missing", message: `Přehled za tento týden zatím není – automaticky vzniká v ${p.schedule_label}.` };
}

/** Tlačítko jen pro aktuální týden; přegenerování vyžaduje potvrzení. Historické týdny jen ke čtení. */
export function generateAction(p: WeeklyPayload | null): { label: string; regenerate: boolean } | null {
  if (!p || !p.can_generate || p.status === "generating") return null;
  return p.review ? { label: "Přegenerovat", regenerate: true } : { label: "Vytvořit přehled", regenerate: false };
}

/** „vysoká jistota" apod. – jistota je pravidlo z dat, ne odhad modelu. */
export function confidenceLabel(confidence: string): string {
  return { high: "vysoká jistota", moderate: "střední jistota", low: "nízká jistota" }[confidence] ?? "jistota neuvedena";
}

/** „Vytvořeno neděle 11. 10. 19:00 (ručně) · přegenerováno 1×". */
export function metaCaption(p: WeeklyPayload): string | null {
  if (!p.generated_label) return null;
  const how = p.trigger === "manual" ? "ručně" : p.trigger === "catchup" ? "dodatečně" : null;
  const parts = [`Vytvořeno ${p.generated_label}${how ? ` (${how})` : ""}`];
  if (p.review?.partial && p.period_end_label) parts.push(`data do ${p.period_end_label}`);
  if (p.regenerated_count > 0) parts.push(`přegenerováno ${p.regenerated_count}×`);
  return parts.join(" · ");
}

/** Zobrazitelný obsah: AI přehled, jinak deterministický náhled z dat (označený). */
export function displayContent(p: WeeklyPayload): { content: WeeklyContent | null; isFallback: boolean } {
  if (p.review) return { content: p.review, isFallback: false };
  return { content: p.fallback, isFallback: Boolean(p.fallback) };
}

