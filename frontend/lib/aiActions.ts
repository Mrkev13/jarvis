/**
 * Akce navržené AI → model pro zobrazení (Roadmap 4C). Jedno místo, které z pending akce (tool + argumenty,
 * nebo náhled `preview` ověřený backendem) udělá kartu „co se změní": název, druh změny, oblast, pole
 * (nové hodnoty), položky staré → nové, počet, upozornění. Sémantika akcí se tu nemění – jen texty.
 * Čisté funkce bez Reactu, testy: aiActions.test.mjs.
 */
import { formatCzkExact, formatDate, formatHours, formatNumber, formatPercent } from "./format.ts";
import { goalStatusMeta } from "./goals.ts";
import {
  aiToolMeta,
  fieldLabel,
  fieldValueLabel,
  financeCategoryLabel,
  memoryCategoryLabel,
  previewEntityArea,
} from "./labels.ts";
import { areaMeta } from "./areas.ts";
import { statusMeta as mffStatusMeta } from "./mff.ts";
import type { PendingAction, PendingPreview } from "./pendingActions.ts";
import { assignmentStatusMeta, examStatusMeta, examTypeLabel } from "./school.ts";
import { priorityTone, type Tone } from "./ui.ts";
import { grindStatusMeta, RESOURCE_LABELS } from "./wot.ts";

export type ActionField = { label: string; value: string };
export type ActionChange = { label: string; old: string; new: string };
export type ActionItem = { label: string; changes: ActionChange[] };

export type ActionView = {
  /** Co se stane („Přidat pracovní záznam", nebo titulek náhledu z backendu). */
  title: string;
  /** Výsledek po potvrzení („Přidán pracovní záznam"). */
  doneTitle: string;
  /** Druh změny pro štítek. */
  kind: "create" | "update" | "delete" | "complete" | "undo";
  kindLabel: string;
  kindTone: Tone;
  /** Oblast (Práce, Finance…) pro AreaBadge; null = obecné. */
  area: string | null;
  /** Nový záznam: hodnoty, které se uloží. */
  fields: ActionField[];
  /** Úprava / smazání / dokončení: dotčené záznamy se změnami staré → nové. */
  items: ActionItem[];
  /** Kolik dalších položek se nevešlo (dávka). */
  hiddenItems: number;
  count: number;
  warnings: string[];
  /** Zvýrazněný souhrn (výdělek, částka, počet záznamů). */
  footer: ActionField | null;
  /** Řádky do zprávy v chatu po potvrzení. */
  detailLines: string[];
};

const MAX_ITEMS = 10;

const KIND: Record<ActionView["kind"], { label: string; tone: Tone }> = {
  create: { label: "Nový záznam", tone: "accent" },
  update: { label: "Úprava", tone: "warning" },
  delete: { label: "Smazání", tone: "danger" },
  complete: { label: "Dokončení", tone: "success" },
  undo: { label: "Vrácení změny", tone: "warning" },
};

function kindOf(raw: string): ActionView["kind"] {
  if (raw === "delete" || raw === "complete" || raw === "undo" || raw === "create") return raw;
  return "update";
}

const str = (v: unknown) => (typeof v === "string" ? v.trim() : v == null ? "" : String(v));
const num = (v: unknown) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const opt = (label: string, value: string): ActionField[] => (value ? [{ label, value }] : []);
const yesNo = (v: unknown, fallback = true) => ((v === undefined ? fallback : Boolean(v)) ? "Ano" : "Ne");

type Described = { fields: ActionField[]; footer: ActionField | null; detailLines: string[]; title?: string };

function describeCreate(tool: string, a: Record<string, unknown>): Described {
  switch (tool) {
    case "add_work_session": {
      const hours = num(a.hours);
      const rate = num(a.hourly_rate);
      const date = formatDate(str(a.date_value) || null);
      const earnings = formatCzkExact(hours * rate);
      return {
        fields: [
          { label: "Datum", value: date },
          { label: "Projekt", value: str(a.project) || "–" },
          { label: "Hodiny", value: formatHours(hours) },
          { label: "Sazba", value: `${formatCzkExact(rate)}/h` },
          ...opt("Poznámka", str(a.description)),
        ],
        footer: { label: "Výdělek", value: earnings },
        detailLines: [date, str(a.project) || "Bez projektu", formatHours(hours), earnings],
      };
    }
    case "add_finance_transaction": {
      const income = str(a.transaction_type) === "income";
      const amount = formatCzkExact(num(a.amount));
      const category = financeCategoryLabel(str(a.category) || "Ostatní");
      return {
        title: income ? "Přidat příjem" : "Přidat výdaj",
        fields: [
          { label: "Typ", value: income ? "Příjem" : "Výdaj" },
          { label: "Částka", value: `${income ? "+" : "−"}${amount}` },
          { label: "Kategorie", value: category },
          ...opt("Popis", str(a.description)),
        ],
        footer: { label: income ? "Příjem" : "Výdaj", value: amount },
        detailLines: [income ? "Příjem" : "Výdaj", amount, `Kategorie: ${category}`, ...(str(a.description) ? [str(a.description)] : [])],
      };
    }
    case "add_school_subject":
      return {
        fields: [
          { label: "Název", value: str(a.name) || "–" },
          ...opt("Zkratka", str(a.code)),
          ...opt("Semestr", str(a.semester)),
          { label: "Kredity", value: String(num(a.credits)) },
          { label: "Aktivní", value: yesNo(a.active) },
        ],
        footer: null,
        detailLines: [str(a.name), ...(str(a.code) ? [str(a.code)] : []), `${num(a.credits)} kreditů`],
      };
    case "add_school_assignment": {
      const due = str(a.due_date);
      const prio = priorityTone(str(a.priority) || "medium").label;
      return {
        fields: [
          { label: "Název", value: str(a.title) || "–" },
          { label: "Předmět", value: `#${str(a.subject_id) || "–"}` },
          ...opt("Termín", due ? formatDate(due) : ""),
          { label: "Priorita", value: prio },
          { label: "Stav", value: assignmentStatusMeta(str(a.status) || "todo").label },
          ...opt("Popis", str(a.description)),
        ],
        footer: null,
        detailLines: [str(a.title), ...(due ? [`Termín: ${formatDate(due)}`] : []), `Priorita: ${prio}`],
      };
    }
    case "add_school_exam": {
      const date = str(a.exam_date);
      const type = examTypeLabel(str(a.exam_type) || "exam");
      return {
        fields: [
          { label: "Název", value: str(a.title) || "–" },
          { label: "Předmět", value: `#${str(a.subject_id) || "–"}` },
          { label: "Typ", value: type },
          ...opt("Datum", date ? formatDate(date) : ""),
          { label: "Stav", value: examStatusMeta(str(a.status) || "upcoming").label },
          ...opt("Poznámky", str(a.notes)),
        ],
        footer: null,
        detailLines: [str(a.title), `${type}${date ? ` – ${formatDate(date)}` : ""}`],
      };
    }
    case "update_wot_resource": {
      const res = RESOURCE_LABELS[str(a.resource) as keyof typeof RESOURCE_LABELS] ?? (str(a.resource) || "–");
      return {
        fields: [
          { label: "Zdroj", value: res },
          { label: "Nové množství", value: formatNumber(num(a.amount), 0) },
        ],
        footer: null,
        detailLines: [`${res}: ${formatNumber(num(a.amount), 0)}`],
      };
    }
    case "upsert_wot_grind": {
      const prio = priorityTone(str(a.priority) || "medium").label;
      const status = grindStatusMeta(str(a.status) || "active").label;
      return {
        fields: [
          { label: "Tank", value: str(a.tank) || "–" },
          { label: "Zbývá XP", value: formatNumber(num(a.xp_remaining), 0) },
          { label: "Priorita", value: prio },
          { label: "Stav", value: status },
        ],
        footer: null,
        detailLines: [str(a.tank), `Zbývá ${formatNumber(num(a.xp_remaining), 0)} XP`, `Priorita: ${prio} · ${status}`],
      };
    }
    case "upsert_mff_character": {
      const build = clamp(num(a.build_completeness), 0, 100);
      const prio = priorityTone(str(a.priority) || "medium").label;
      const status = mffStatusMeta(str(a.status) || "built").label;
      const tier = str(a.tier) || "T3";
      return {
        fields: [
          { label: "Postava", value: str(a.name) || "–" },
          { label: "Tier", value: tier },
          { label: "Level", value: String(num(a.level)) },
          ...opt("Uniform", str(a.uniform)),
          ...opt("CTP", str(a.ctp)),
          ...opt("Artifact", str(a.artifact)),
          ...opt("Role", str(a.role)),
          ...opt("Tým", str(a.team)),
          ...opt("Uru", str(a.uru_state)),
          ...opt("ISO-8", str(a.iso8_set)),
          { label: "Kompletnost buildu", value: formatPercent(build) },
          { label: "Priorita", value: prio },
          { label: "Stav", value: status },
          ...opt("Poznámky", str(a.notes)),
        ],
        footer: null,
        detailLines: [`${str(a.name)} (${tier}, Lv. ${num(a.level)})`, `Build ${formatPercent(build)} · ${prio} · ${status}`],
      };
    }
    case "upsert_goal": {
      const progress = clamp(num(a.progress), 0, 100);
      const prio = priorityTone(str(a.priority) || "medium").label;
      const target = str(a.target_date);
      const area = areaMeta(str(a.area) || null).label;
      return {
        title: a.id ? "Upravit cíl" : "Přidat cíl",
        fields: [
          ...opt("Cíl", a.id ? `#${str(a.id)}` : ""),
          { label: "Oblast", value: area },
          { label: "Název", value: str(a.title) || "–" },
          { label: "Stav", value: goalStatusMeta(str(a.status) || "active").label },
          { label: "Priorita", value: prio },
          ...opt("Cílové datum", target ? formatDate(target) : ""),
          ...opt("Popis", str(a.description)),
        ],
        footer: { label: "Postup", value: formatPercent(progress) },
        detailLines: [str(a.title), `${area} · Priorita: ${prio}`, `Postup ${formatPercent(progress)}${target ? ` · do ${formatDate(target)}` : ""}`],
      };
    }
    case "save_memory": {
      const importance = clamp(num(a.importance) || 5, 1, 10);
      const area = areaMeta(str(a.area) || "general").label;
      const category = memoryCategoryLabel(str(a.category) || "context");
      return {
        fields: [
          { label: "Oblast", value: area },
          { label: "Kategorie", value: category },
          { label: "Obsah", value: str(a.content) || "–" },
          { label: "Důležitost", value: `${importance}/10` },
          { label: "Aktivní", value: yesNo(a.active) },
        ],
        footer: null,
        detailLines: [`${area} · ${category}`, str(a.content) || "–", `Důležitost ${importance}/10`],
      };
    }
    default:
      // Neznámý tool: hodnoty s českými názvy polí, interní klíče se neukazují surově.
      return {
        fields: Object.entries(a)
          .filter(([, v]) => v !== null && v !== undefined && v !== "" && typeof v !== "object")
          .map(([k, v]) => ({ label: fieldLabel(k), value: fieldValueLabel(k, v) })),
        footer: null,
        detailLines: [],
      };
  }
}

function fromPreview(action: PendingAction, preview: PendingPreview): ActionView {
  const kind = kindOf(preview.kind);
  const meta = aiToolMeta(action.tool);
  const items = preview.items.map((i) => ({ label: i.label, changes: i.changes }));
  const shown = items.slice(0, MAX_ITEMS);
  return {
    title: preview.title,
    doneTitle: preview.title,
    kind,
    kindLabel: KIND[kind].label,
    kindTone: KIND[kind].tone,
    area: previewEntityArea(preview.entity) ?? meta.area,
    fields: [],
    items: shown,
    hiddenItems: Math.max(0, items.length - MAX_ITEMS),
    count: preview.count,
    warnings: preview.warnings,
    footer: preview.count > 1 || kind === "delete" ? { label: "Počet záznamů", value: String(preview.count) } : null,
    detailLines: [...shown.map((i) => i.label), ...(preview.count > 1 ? [`Záznamů: ${preview.count}`] : [])],
  };
}

/** Pending akce → model karty. Náhled z backendu má přednost (úpravy, mazání, připomínky, vrácení). */
export function describeAction(action: PendingAction): ActionView {
  if (action.preview) return fromPreview(action, action.preview);
  const meta = aiToolMeta(action.tool);
  const d = describeCreate(action.tool, action.arguments ?? {});
  return {
    title: d.title ?? meta.action,
    doneTitle: meta.done,
    kind: "create",
    kindLabel: KIND.create.label,
    kindTone: KIND.create.tone,
    area: meta.area,
    fields: d.fields,
    items: [],
    hiddenItems: 0,
    count: 1,
    warnings: [],
    footer: d.footer,
    detailLines: d.detailLines.filter(Boolean),
  };
}

/** Zpráva do chatu po potvrzení / zamítnutí (ukládá se do historie konverzace). */
export function confirmedMessage(view: ActionView, fromPreview: boolean): string {
  const head = fromPreview ? `✅ Hotovo – ${view.title}.` : `✅ ${view.doneTitle}.`;
  return view.detailLines.length ? `${head}\n\n${view.detailLines.join("\n")}` : head;
}

export function rejectedMessage(view: ActionView | null): string {
  return `❌ Akce byla zrušena${view ? `: ${view.title}` : ""}.`;
}
