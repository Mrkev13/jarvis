/**
 * Řídicí centrum na míru (Roadmap 4F) – čistá logika rozložení bez Reactu (testy: dashboardLayout.test.mjs).
 *
 * Registr widgetů je EXPLICITNÍ seznam (žádné objevování modulů za běhu). Uložené rozložení obsahuje jen
 * sémantiku – id, viditelnost, pořadí, velikost – nikdy pixely ani CSS. Každá breakpointová podoba se z něj
 * odvozuje: mobil 1 sloupec v pořadí, tablet 2 sloupce, desktop 6 jednotek (packDesktop).
 *
 * Roadmap 6C: widget může patřit modulům (`modules`). Widget vypnutého modulu se do rozložení vůbec nedostane
 * (nevykreslí se, nic nenačte, není ani mezi „Skrytými"), ale jeho uložený záznam zůstane v úložišti beze změny
 * (`preserveUnavailable`) – po opětovném zapnutí se vrátí na své místo s uloženou viditelností a velikostí.
 *
 * MRK-78: Řídicí centrum = jedna hlavní denní obrazovka. Nahoře „Co hoří" a „Můj den" (jádro /today), pak Cíle
 * a Hry, Klíčová čísla dole. Starší bloky Dnes (plánovač), Vyžaduje pozornost a Nadcházející by ukazovaly totéž
 * podruhé, proto jsou ve výchozím stavu skryté (dají se vrátit). Rozložení verze 1 se převede (`migrateV1`).
 */
import { MODULE_UI, MODULES, type ModuleAccess } from "./modules.ts";

export type WidgetSize = "small" | "medium" | "large" | "full";

export const WIDGET_SIZES: WidgetSize[] = ["small", "medium", "large", "full"];

export const SIZE_LABELS: Record<WidgetSize, string> = {
  small: "Malý",
  medium: "Střední",
  large: "Velký",
  full: "Celá šířka",
};

/** Šířka na desktopu v jednotkách ze 6: třetina, polovina, dvě třetiny, celý řádek. */
export const DESKTOP_UNITS: Record<WidgetSize, number> = { small: 2, medium: 3, large: 4, full: 6 };
export const DESKTOP_COLUMNS = 6;
/** Tablet: 2 sloupce – malý a střední = 1, velký a celá šířka = 2. */
export const TABLET_SPAN: Record<WidgetSize, 1 | 2> = { small: 1, medium: 1, large: 2, full: 2 };

/** Id widgetů JÁDRA a starších modulů (stabilní, ukládají se natrvalo). Komponenty: components/dashboard/widgets.tsx.
 * Widgety modulů z balíčků modules/<id>/ dodává `MODULE_UI.<id>.widgets` (komponenty v modules/registry.tsx). */
export const WIDGET_IDS = [
  "burning",
  "day",
  "changes",
  "daily_briefing",
  "weekly_review",
  "today",
  "attention",
  "key_metrics",
  "goals",
  "upcoming",
  "work",
  "finance",
  "games",
  "quick_actions",
] as const;
export type WidgetId = (typeof WIDGET_IDS)[number];

export interface WidgetDef {
  /** Stabilní sémantické id – ukládá se natrvalo, nikdy ho neměnit ani nepoužívat indexy. */
  id: string;
  title: string;
  area: string | null;
  defaultVisible: boolean;
  defaultOrder: number;
  defaultSize: WidgetSize;
  allowedSizes: WidgetSize[];
  /** Widget čte společný payload GET /dashboard (skrytím všech takových se dotaz vůbec nepošle). */
  usesDashboardData: boolean;
  /** Moduly widgetu (Roadmap 6C): dostupný, když aspoň jeden smí na dashboard. Bez nich = jádro. */
  modules?: string[];
  /** MRK-78: widget čte GET /today (načte se jednou pro všechny takové widgety). */
  usesToday?: boolean;
  /**
   * MRK-104: do existujícího uloženého rozložení (v1 i v2), ve kterém widget chybí, se doplní SKRYTÝ – uložená volba
   * se nemění, zapne se v úpravách. `defaultVisible` platí jen pro čerstvé výchozí rozložení (bez uložené volby).
   */
  hiddenInStoredLayouts?: boolean;
}

export const CORE_WIDGETS: WidgetDef[] = [
  { id: "burning", title: "Co hoří", area: null, defaultVisible: true, defaultOrder: 10, defaultSize: "medium", allowedSizes: ["medium", "large", "full"], usesDashboardData: true, usesToday: true },
  { id: "day", title: "Můj den", area: null, defaultVisible: true, defaultOrder: 20, defaultSize: "medium", allowedSizes: ["medium", "large", "full"], usesDashboardData: false, usesToday: true },
  { id: "goals", title: "Cíle", area: "goals", defaultVisible: true, defaultOrder: 30, defaultSize: "medium", allowedSizes: ["small", "medium", "large"], usesDashboardData: true, modules: ["goals"] },
  { id: "games", title: "Hry", area: null, defaultVisible: true, defaultOrder: 40, defaultSize: "full", allowedSizes: ["medium", "large", "full"], usesDashboardData: true, modules: ["wot", "mff"] },
  { id: "daily_briefing", title: "Denní přehled", area: "briefing", defaultVisible: true, defaultOrder: 50, defaultSize: "large", allowedSizes: ["medium", "large", "full"], usesDashboardData: false },
  { id: "weekly_review", title: "Týdenní přehled", area: "review", defaultVisible: true, defaultOrder: 60, defaultSize: "small", allowedSizes: ["small", "medium"], usesDashboardData: false },
  { id: "changes", title: "Od včera", area: null, defaultVisible: true, defaultOrder: 70, defaultSize: "large", allowedSizes: ["medium", "large", "full"], usesDashboardData: false },
  { id: "work", title: "Práce", area: "work", defaultVisible: true, defaultOrder: 80, defaultSize: "small", allowedSizes: ["small", "medium"], usesDashboardData: true, modules: ["work"] },
  { id: "finance", title: "Finance", area: "finance", defaultVisible: true, defaultOrder: 90, defaultSize: "small", allowedSizes: ["small", "medium"], usesDashboardData: true, modules: ["finance"] },
  { id: "key_metrics", title: "Klíčová čísla", area: null, defaultVisible: true, defaultOrder: 100, defaultSize: "full", allowedSizes: ["large", "full"], usesDashboardData: true, modules: ["work", "finance"] },
  { id: "quick_actions", title: "Rychlé akce", area: null, defaultVisible: true, defaultOrder: 110, defaultSize: "full", allowedSizes: ["large", "full"], usesDashboardData: false },
  // MRK-78: nahrazené bloky – stejný obsah ukazují „Co hoří" a „Můj den"; skryté, ale dají se vrátit
  { id: "today", title: "Plán dne", area: null, defaultVisible: false, defaultOrder: 120, defaultSize: "large", allowedSizes: ["medium", "large", "full"], usesDashboardData: true },
  { id: "attention", title: "Vyžaduje pozornost", area: null, defaultVisible: false, defaultOrder: 130, defaultSize: "small", allowedSizes: ["small", "medium", "large"], usesDashboardData: true },
  { id: "upcoming", title: "Nadcházející", area: "school", defaultVisible: false, defaultOrder: 140, defaultSize: "small", allowedSizes: ["small", "medium", "large"], usesDashboardData: true, modules: ["school"] },
];

/** MRK-21: widgety z manifestů modulů (jen implementované moduly). */
export const MODULE_WIDGETS: WidgetDef[] = MODULES.filter((m) => m.implemented).flatMap((m) => MODULE_UI[m.id]?.widgets ?? []);

/** Celý registr: jádro + moduly (výchozí pořadí řeší `defaultOrder`). */
export const WIDGETS: WidgetDef[] = [...CORE_WIDGETS, ...MODULE_WIDGETS];

/** Widgety, které smí aktuální moduly ukázat (pořadí registru). */
export function availableWidgets(access: ModuleAccess, defs: WidgetDef[] = WIDGETS): WidgetDef[] {
  return defs.filter((d) => access.allowsAny(d.modules, "dashboard"));
}

export const LAYOUT_VERSION = 2;
/** Klíč zůstává „v1" (verze rozložení je uvnitř hodnoty) – starší uložené rozložení se tak najde a převede. */
export const LAYOUT_STORAGE_KEY = "standa-hub:dashboard-layout:v1";

export interface WidgetLayout {
  id: string;
  visible: boolean;
  order: number;
  size: WidgetSize;
}

export interface DashboardLayout {
  version: typeof LAYOUT_VERSION;
  widgets: WidgetLayout[];
}

const ORDER_STEP = 10;

function byDefaultOrder(defs: WidgetDef[]): WidgetDef[] {
  return [...defs].sort((a, b) => a.defaultOrder - b.defaultOrder);
}

/** Pořadí přečíslované 10, 20, 30… (seřazeno podle `order`). */
function renumber(widgets: WidgetLayout[]): WidgetLayout[] {
  return [...widgets]
    .sort((a, b) => a.order - b.order)
    .map((w, i) => ({ ...w, order: (i + 1) * ORDER_STEP }));
}

export function defaultLayout(defs: WidgetDef[] = WIDGETS): DashboardLayout {
  return {
    version: LAYOUT_VERSION,
    widgets: renumber(byDefaultOrder(defs).map((d) => ({ id: d.id, visible: d.defaultVisible, order: d.defaultOrder, size: d.defaultSize }))),
  };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** MRK-78: bloky, které nové Řídicí centrum nahradilo – při převodu z verze 1 se skryjí (nic se nemaže). */
export const REPLACED_IN_V2 = ["today", "attention", "upcoming"];

/**
 * MRK-78: rozložení verze 1 → verze 2. Viditelnost a velikost uložených widgetů zůstanou, pořadí převezme nové
 * výchozí (Co hoří a Můj den nahoře, Klíčová čísla dole) a nahrazené bloky se skryjí, aby nic nebylo dvakrát.
 * Neznámá id projdou beze změny (zahodí je až normalizace), nové widgety doplní `normalizeLayout`.
 */
export function migrateV1(raw: Record<string, unknown>, defs: WidgetDef[] = WIDGETS): Record<string, unknown> {
  const order = new Map(defs.map((d) => [d.id, d.defaultOrder]));
  const widgets = (raw.widgets as unknown[]).map((item, index) => {
    if (!isRecord(item) || typeof item.id !== "string") return item;
    const visible = REPLACED_IN_V2.includes(item.id) ? false : item.visible;
    return { ...item, visible, order: order.get(item.id) ?? 1000 + index };
  });
  return { version: LAYOUT_VERSION, widgets };
}

/**
 * Uložené rozložení → platné rozložení. Nikdy nevyhodí výjimku:
 * - jiná verze / nesmyslná struktura → výchozí rozložení;
 * - neznámá (zastaralá) id a duplicity (platí první výskyt) se zahodí;
 * - neplatná velikost → výchozí velikost widgetu; neplatná viditelnost / pořadí → výchozí hodnota;
 * - widget, který v uloženém rozložení chybí (např. nový), se vloží za svého předchůdce ve výchozím pořadí –
 *   viditelný podle `defaultVisible`, nebo skrytý, když má `hiddenInStoredLayouts` (MRK-104).
 */
export function normalizeLayout(raw: unknown, defs: WidgetDef[] = WIDGETS): DashboardLayout {
  if (isRecord(raw) && raw.version === 1 && Array.isArray(raw.widgets)) raw = migrateV1(raw, defs);
  if (!isRecord(raw) || raw.version !== LAYOUT_VERSION || !Array.isArray(raw.widgets)) return defaultLayout(defs);
  const defById = new Map(defs.map((d) => [d.id, d]));
  const seen = new Set<string>();
  const kept: WidgetLayout[] = [];
  raw.widgets.forEach((item, index) => {
    if (!isRecord(item) || typeof item.id !== "string") return;
    const def = defById.get(item.id);
    if (!def || seen.has(item.id)) return;
    seen.add(item.id);
    const size = WIDGET_SIZES.includes(item.size as WidgetSize) && def.allowedSizes.includes(item.size as WidgetSize) ? (item.size as WidgetSize) : def.defaultSize;
    kept.push({
      id: def.id,
      visible: typeof item.visible === "boolean" ? item.visible : def.defaultVisible,
      // nečíselné pořadí → pozice v poli (stabilní řazení zachová zbytek)
      order: typeof item.order === "number" && Number.isFinite(item.order) ? item.order : (index + 1) * ORDER_STEP,
      size,
    });
  });
  if (kept.length === 0) return defaultLayout(defs);

  // Chybějící widgety: za předchůdce ve výchozím pořadí, jinak na začátek.
  let ordered = renumber(kept);
  const defaults = byDefaultOrder(defs);
  for (const def of defaults) {
    if (seen.has(def.id)) continue;
    const before = defaults.slice(0, defaults.indexOf(def)).reverse().find((d) => seen.has(d.id));
    const at = before ? ordered.findIndex((w) => w.id === before.id) + 1 : 0;
    const visible = def.hiddenInStoredLayouts ? false : def.defaultVisible;
    ordered = [...ordered.slice(0, at), { id: def.id, visible, order: 0, size: def.defaultSize }, ...ordered.slice(at)];
    ordered = ordered.map((w, i) => ({ ...w, order: (i + 1) * ORDER_STEP }));
    seen.add(def.id);
  }
  return { version: LAYOUT_VERSION, widgets: ordered };
}

/** localStorage řetězec → rozložení (poškozený JSON / nic → výchozí). */
export function parseStoredLayout(raw: string | null, defs: WidgetDef[] = WIDGETS): DashboardLayout {
  if (!raw) return defaultLayout(defs);
  try {
    return normalizeLayout(JSON.parse(raw), defs);
  } catch {
    return defaultLayout(defs);
  }
}

/**
 * Před uložením vrátí do rozložení záznamy widgetů, které jsou v registru, ale teď nedostupné (vypnutý modul) –
 * každý za widget, který mu v předchozím uloženém rozložení předcházel (jinak na konec). Úpravy dashboardu
 * s vypnutým modulem tak nesmažou jeho uložené nastavení. Neznámá id (smazané widgety) se dál zahazují.
 */
export function preserveUnavailable(next: DashboardLayout, previousRaw: string | null, available: WidgetDef[], defs: WidgetDef[] = WIDGETS): DashboardLayout {
  if (!previousRaw) return next;
  const previous = parseStoredLayout(previousRaw, defs);
  const availableIds = new Set(available.map((d) => d.id));
  let widgets = [...next.widgets];
  previous.widgets.forEach((w, index) => {
    if (availableIds.has(w.id) || widgets.some((x) => x.id === w.id)) return;
    const before = previous.widgets.slice(0, index).reverse().find((p) => widgets.some((x) => x.id === p.id));
    const at = before ? widgets.findIndex((x) => x.id === before.id) + 1 : widgets.length;
    widgets = [...widgets.slice(0, at), w, ...widgets.slice(at)];
  });
  return { version: LAYOUT_VERSION, widgets: widgets.map((w, i) => ({ ...w, order: (i + 1) * ORDER_STEP })) };
}

export function serializeLayout(layout: DashboardLayout): string {
  return JSON.stringify({ version: layout.version, widgets: layout.widgets.map(({ id, visible, order, size }) => ({ id, visible, order, size })) });
}

export function isDefaultLayout(layout: DashboardLayout, defs: WidgetDef[] = WIDGETS): boolean {
  return serializeLayout(layout) === serializeLayout(defaultLayout(defs));
}

export function visibleWidgets(layout: DashboardLayout): WidgetLayout[] {
  return layout.widgets.filter((w) => w.visible);
}

export function hiddenWidgets(layout: DashboardLayout): WidgetLayout[] {
  return layout.widgets.filter((w) => !w.visible);
}

/**
 * Posun mezi VIDITELNÝMI widgety (skryté pořadí nemění „mezeru" – prohodí se s nejbližším viditelným sousedem).
 * Na okraji se nic nestane (vrací stejný objekt).
 */
export function moveWidget(layout: DashboardLayout, id: string, direction: -1 | 1): DashboardLayout {
  const list = renumber(layout.widgets);
  const from = list.findIndex((w) => w.id === id);
  if (from < 0 || !list[from].visible) return layout;
  let to = from + direction;
  while (to >= 0 && to < list.length && !list[to].visible) to += direction;
  if (to < 0 || to >= list.length) return layout;
  const next = [...list];
  [next[from], next[to]] = [next[to], next[from]];
  return { version: LAYOUT_VERSION, widgets: next.map((w, i) => ({ ...w, order: (i + 1) * ORDER_STEP })) };
}

export function setWidgetVisible(layout: DashboardLayout, id: string, visible: boolean): DashboardLayout {
  if (!layout.widgets.some((w) => w.id === id)) return layout;
  return { ...layout, widgets: layout.widgets.map((w) => (w.id === id ? { ...w, visible } : w)) };
}

/** Jen povolená velikost widgetu; jinak beze změny. */
export function setWidgetSize(layout: DashboardLayout, id: string, size: WidgetSize, defs: WidgetDef[] = WIDGETS): DashboardLayout {
  const def = defs.find((d) => d.id === id);
  if (!def || !def.allowedSizes.includes(size)) return layout;
  return { ...layout, widgets: layout.widgets.map((w) => (w.id === id ? { ...w, size } : w)) };
}

/** Pozice mezi viditelnými (1-based) – pro hlášení čtečce a zakázání tlačítek na okraji. */
export function visiblePosition(layout: DashboardLayout, id: string): { index: number; count: number } {
  const visible = renumber(layout.widgets).filter((w) => w.visible);
  return { index: visible.findIndex((w) => w.id === id) + 1, count: visible.length };
}

export function needsDashboardData(layout: DashboardLayout, defs: WidgetDef[] = WIDGETS): boolean {
  const uses = new Set(defs.filter((d) => d.usesDashboardData).map((d) => d.id));
  return layout.widgets.some((w) => w.visible && uses.has(w.id));
}

/** MRK-78: GET /today jen když je vidět widget, který ho čte. */
export function needsToday(layout: DashboardLayout, defs: WidgetDef[] = WIDGETS): boolean {
  const uses = new Set(defs.filter((d) => d.usesToday).map((d) => d.id));
  return layout.widgets.some((w) => w.visible && uses.has(w.id));
}

// ---------- desktopové bloky ----------

export interface DesktopBlock {
  /** šířky sloupců v jednotkách (součet ≤ 6) */
  columns: { units: number; ids: string[] }[];
}

/**
 * Desktop (6 jednotek): řádky se plní v pořadí; další řádek se NEPŘIDÁ pod ten předchozí jako nový řádek,
 * ale do jeho sloupců, pokud jeho velikosti odpovídají konci předchozího řádku (stejné šířky zprava).
 * Výchozí vyvážení (MRK-78, MRK-104): [Co hoří | Můj den], [Návyky | Cíle], [Hry], pak [Denní přehled | Týdenní přehled] +
 * [Od včera | Práce] + [Finance] → vlevo přehled + změny, vpravo týden, Práce a Finance pod sebou.
 * Karty ve sloupci se skládají pod sebe bez děr, nic se neroztahuje.
 */
export function packDesktop(widgets: { id: string; size: WidgetSize }[]): DesktopBlock[] {
  const rows: { id: string; units: number }[][] = [];
  let row: { id: string; units: number }[] = [];
  let used = 0;
  for (const w of widgets) {
    const units = DESKTOP_UNITS[w.size];
    if (used + units > DESKTOP_COLUMNS && row.length) {
      rows.push(row);
      row = [];
      used = 0;
    }
    row.push({ id: w.id, units });
    used += units;
  }
  if (row.length) rows.push(row);

  const blocks: DesktopBlock[] = [];
  for (const r of rows) {
    const last = blocks[blocks.length - 1];
    if (last && r.length < last.columns.length + 1) {
      const offset = last.columns.length - r.length;
      const fits = offset >= 0 && r.every((item, i) => last.columns[offset + i].units === item.units);
      if (fits) {
        r.forEach((item, i) => last.columns[offset + i].ids.push(item.id));
        continue;
      }
    }
    blocks.push({ columns: r.map((item) => ({ units: item.units, ids: [item.id] })) });
  }
  return blocks;
}
