/**
 * Prezentační popisky interních hodnot (Roadmap 4B.1) – JEDNO místo pro překlad toho, co backend ukládá
 * (typy entit, názvy polí, kategorie, enumy), do češtiny pro UI. Uložené hodnoty, API ani payloady se nemění.
 * Neznámá hodnota se nikdy neztratí: vrátí se čitelně upravená původní hodnota. Testy: labels.test.mjs.
 */

import { AREA_STYLES } from "./areas.ts";

/** Klíč pro vyhledání: malá písmena, bez okrajových mezer. */
const key = (value: string | null | undefined) => String(value ?? "").trim().toLowerCase();

/** Neznámá hodnota: ořezaná, s velkým prvním písmenem („jídlo" → „Jídlo"); prázdná → „–". */
export function fallbackLabel(value: string | null | undefined): string {
  const v = String(value ?? "").trim();
  return v ? v.charAt(0).toLocaleUpperCase("cs-CZ") + v.slice(1) : "–";
}

function lookup(map: Record<string, string>, value: string | null | undefined): string {
  return map[key(value)] ?? fallbackLabel(value);
}

// ---------- typy entit v auditu (activity_log.entity_type) ----------

const ENTITY_LABELS: Record<string, string> = {
  assignment: "Úkol",
  exam: "Zkouška",
  subject: "Předmět",
  financetransaction: "Transakce",
  worksession: "Pracovní záznam",
  goal: "Cíl",
  memory: "Paměť",
  reminder: "Připomínka",
  wotgrind: "Grind",
  wotresource: "Zdroj WoT",
  mffcharacter: "Postava",
  pendingaction: "Návrh AI",
  toolregistry: "Nástroj AI",
  // akce AI (audit „ai" ukládá jako typ entity název nástroje – backend tool_registry WRITE_SPECS)
  add_work_session: "Zápis práce",
  add_finance_transaction: "Zápis transakce",
  add_school_subject: "Nový předmět",
  add_school_assignment: "Nový úkol",
  add_school_exam: "Nová zkouška",
  update_wot_resource: "Zdroje WoT",
  upsert_wot_grind: "Grind",
  upsert_mff_character: "Postava MFF",
  upsert_goal: "Cíl",
  save_memory: "Paměť",
  modify_records: "Úprava záznamů",
  add_reminder: "Nová připomínka",
  manage_reminder: "Správa připomínky",
  undo_change: "Vrácení změny",
};

/** „WotGrind" → „Grind"; neznámé (např. název nástroje AI) zůstává beze změny. */
export function entityTypeLabel(entityType: string | null | undefined): string {
  return ENTITY_LABELS[key(entityType)] ?? String(entityType ?? "").trim();
}

/** „Grind #6" / „Transakce #12" – pro meta řádek v Aktivitě. */
export function entityRefLabel(entityType: string | null | undefined, entityId: number | null | undefined): string {
  const label = entityTypeLabel(entityType);
  return entityId == null ? label : `${label} #${entityId}`;
}

/** Odkud změna přišla (activity_log.user_context). */
const SOURCE_LABELS: Record<string, string> = {
  manual: "ručně",
  ai_confirm: "AI, potvrzeno",
  ai: "AI",
  scheduler: "plánovač",
  system: "systém",
};

export function activitySourceLabel(source: string | null | undefined): string {
  return SOURCE_LABELS[key(source)] ?? String(source ?? "").trim();
}

// ---------- názvy polí v detailu změny (delta) ----------

const FIELD_LABELS: Record<string, string> = {
  active: "Aktivní",
  amount: "Částka",
  area: "Oblast",
  build_completeness: "Kompletnost buildu",
  category: "Kategorie",
  code: "Kód",
  content: "Obsah",
  credits: "Kredity",
  date: "Datum",
  deadline: "Termín",
  description: "Popis",
  due_at: "Termín",
  due_date: "Termín",
  exam_date: "Datum zkoušky",
  exam_type: "Typ zkoušky",
  hourly_rate: "Hodinová sazba",
  hours: "Hodiny",
  importance: "Důležitost",
  name: "Název",
  notes: "Poznámky",
  priority: "Priorita",
  progress: "Postup",
  project: "Projekt",
  resource: "Zdroj",
  semester: "Semestr",
  source: "Zdroj dat",
  status: "Stav",
  subject_id: "Předmět",
  sync_to_finance: "Zapsat do financí",
  tank: "Tank",
  target_date: "Cílové datum",
  target_value: "Cílová hodnota",
  tier: "Tier",
  title: "Název",
  tracking_type: "Sledování",
  transaction_type: "Typ",
  xp_remaining: "Zbývá XP",
  // vrácení změn AI
  undo_of_action: "Vrácená akce",
  restored: "Obnoveno",
  entity: "Záznam",
  action: "Akce",
  ids: "ID",
};

/** „amount" → „Částka"; neznámé snake_case → „Some field" (čitelné, bez podtržítek). */
export function fieldLabel(field: string): string {
  return FIELD_LABELS[key(field)] ?? fallbackLabel(field.replace(/_/g, " "));
}

// ---------- kategorie ----------

/** Finance: kategorie je volný text; známé (anglické i systémové jako „work" ze synchronizace práce) → česky. */
const FINANCE_CATEGORY_LABELS: Record<string, string> = {
  work: "Práce",
  salary: "Výplata",
  income: "Příjem",
  food: "Jídlo",
  groceries: "Potraviny",
  rent: "Nájem",
  housing: "Bydlení",
  utilities: "Energie",
  energy: "Energie",
  transport: "Doprava",
  travel: "Cestování",
  entertainment: "Zábava",
  fun: "Zábava",
  shopping: "Nákupy",
  health: "Zdraví",
  sport: "Sport",
  education: "Vzdělání",
  school: "Škola",
  subscriptions: "Předplatné",
  subscription: "Předplatné",
  gifts: "Dárky",
  savings: "Spoření",
  investment: "Investice",
  bills: "Účty",
  other: "Ostatní",
};

export function financeCategoryLabel(category: string | null | undefined): string {
  return lookup(FINANCE_CATEGORY_LABELS, category);
}

/** Paměť: kategorie poznámek (AI i ručně; volný text). */
const MEMORY_CATEGORY_LABELS: Record<string, string> = {
  context: "Kontext",
  preference: "Preference",
  plan: "Plán",
  decision: "Rozhodnutí",
  routine: "Rutina",
  constraint: "Omezení",
  goal: "Cíl",
  fact: "Fakt",
  habit: "Zvyk",
  rule: "Pravidlo",
  note: "Poznámka",
  idea: "Nápad",
  person: "Osoba",
  schedule: "Rozvrh",
  health: "Zdraví",
  work: "Práce",
  school: "Škola",
  finance: "Finance",
};

export function memoryCategoryLabel(category: string | null | undefined): string {
  return lookup(MEMORY_CATEGORY_LABELS, category);
}

// ---------- hodnoty polí v detailu změny ----------

const STATUS_LABELS: Record<string, string> = {
  todo: "K vypracování",
  in_progress: "Rozpracováno",
  done: "Hotovo",
  upcoming: "Nadcházející",
  passed: "Splněno",
  failed: "Nesplněno",
  active: "Aktivní",
  paused: "Pozastaveno",
  completed: "Dokončeno",
  cancelled: "Zrušeno",
  planned: "Plánováno",
  building: "Rozpracováno",
  built: "Postaveno",
  inactive: "Neaktivní",
  scheduled: "Naplánováno",
  fired: "Spuštěno",
};

const VALUE_LABELS: Record<string, Record<string, string>> = {
  status: STATUS_LABELS,
  priority: { high: "Vysoká", medium: "Střední", low: "Nízká" },
  transaction_type: { income: "Příjem", expense: "Výdaj" },
  tracking_type: { manual: "Ručně", automatic: "Automaticky" },
};

/**
 * Hodnota pole pro detail změny: booleany → Ano/Ne, enumy a kategorie → česky, čísla s desetinnou čárkou,
 * ostatní beze změny. `entityType` rozliší kategorii transakce a poznámky.
 */
export function fieldValueLabel(field: string, value: unknown, entityType?: string | null): string {
  if (value == null || value === "") return "–";
  if (typeof value === "boolean") return value ? "Ano" : "Ne";
  if (typeof value === "number") return new Intl.NumberFormat("cs-CZ", { maximumFractionDigits: 2 }).format(value);
  if (typeof value === "object") return JSON.stringify(value);
  const f = key(field);
  const v = String(value);
  if (f === "area") return AREA_STYLES[key(v)]?.label ?? fallbackLabel(v);
  if (f === "category") {
    const e = key(entityType);
    if (e === "financetransaction") return financeCategoryLabel(v);
    if (e === "memory") return memoryCategoryLabel(v);
  }
  return VALUE_LABELS[f]?.[key(v)] ?? v;
}
