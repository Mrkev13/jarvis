/**
 * Rychlé přidání (Roadmap 4E) – čistá logika bez Reactu (testuje se přes `node --test`, viz quickAdd.test.mjs).
 *
 * Tok: POST /quick-add/parse {text} → náhled (backend quick_add_service.parse, deterministicky, bez zápisu)
 *      → uživatel případně doplní / opraví pole → „Uložit"
 *      → POST /quick-add/prepare {kind, fields} (server znovu ověří a vytvoří BĚŽNOU pending akci)
 *      → POST /actions/confirm {action_id} (stejná cesta jako potvrzení návrhu AI).
 *
 * Nic se neuhaduje potichu: `needs_input` (otázka) musí uživatel vyřešit – vyplnit pole, nebo potvrdit
 * navrženou hodnotu („Je to 820 Kč?" → „Ano"). Enter v poli jen znovu rozebere text, nikdy neukládá.
 */

export type QuickAddKind = "reminder" | "finance" | "work" | "exam" | "assignment";
export type ParsedKind = QuickAddKind | "unknown" | "empty";
export type Confidence = "high" | "medium" | "low";

export interface QuickAddIssue {
  field: string;
  message: string;
}

export interface QuickAddQuestion {
  field: string;
  question: string;
}

export interface QuickAddParse {
  kind: ParsedKind;
  confidence: Confidence;
  fields: Record<string, unknown>;
  display: { title: string; subtitle: string; area: string | null };
  warnings: string[];
  needs_input: QuickAddQuestion[];
  errors: QuickAddIssue[];
  ready: boolean;
  subjects?: { id: number; name: string }[];
}

export type FieldType = "text" | "number" | "date" | "datetime" | "select" | "checkbox" | "subject";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: { value: string; label: string }[];
  /** krok / jednotka u čísel (jen nápověda pro vstup) */
  step?: string;
  suffix?: string;
}

export const QUICK_ADD_KINDS: QuickAddKind[] = ["reminder", "finance", "work", "exam", "assignment"];

export const KIND_LABELS: Record<QuickAddKind, string> = {
  reminder: "Připomínka",
  finance: "Finance",
  work: "Práce",
  exam: "Zkouška",
  assignment: "Úkol",
};

export const KIND_AREAS: Record<QuickAddKind, string> = {
  reminder: "reminders",
  finance: "finance",
  work: "work",
  exam: "school",
  assignment: "school",
};

export const KIND_HREFS: Record<QuickAddKind, string> = {
  reminder: "/reminders",
  finance: "/finance",
  work: "/work",
  exam: "/school",
  assignment: "/school",
};

/** Jistota rozpoznání slovy – nikdy ne číselné skóre. */
export const CONFIDENCE_META: Record<Confidence, { label: string; tone: "success" | "warning" | "danger" }> = {
  high: { label: "Rozpoznáno", tone: "success" },
  medium: { label: "Zkontroluj", tone: "warning" },
  low: { label: "Nejisté", tone: "danger" },
};

export const FIELD_DEFS: Record<QuickAddKind, FieldDef[]> = {
  reminder: [
    { key: "title", label: "Co připomenout", type: "text", required: true },
    { key: "due_local", label: "Kdy", type: "datetime", required: true },
  ],
  finance: [
    {
      key: "transaction_type",
      label: "Typ",
      type: "select",
      required: true,
      options: [
        { value: "expense", label: "Výdaj" },
        { value: "income", label: "Příjem" },
      ],
    },
    { key: "amount", label: "Částka", type: "number", required: true, step: "0.01", suffix: "Kč" },
    { key: "category", label: "Kategorie", type: "text" },
    { key: "description", label: "Popis", type: "text" },
  ],
  work: [
    { key: "hours", label: "Hodiny", type: "number", required: true, step: "0.25", suffix: "h" },
    { key: "project", label: "Projekt", type: "text" },
    { key: "hourly_rate", label: "Sazba", type: "number", step: "1", suffix: "Kč/h" },
    { key: "date", label: "Datum", type: "date", required: true },
    { key: "sync_to_finance", label: "Zapsat výdělek do Financí", type: "checkbox" },
  ],
  exam: [
    { key: "title", label: "Název", type: "text", required: true },
    { key: "subject_id", label: "Předmět", type: "subject", required: true },
    {
      key: "exam_type",
      label: "Druh",
      type: "select",
      options: [
        { value: "exam", label: "Zkouška" },
        { value: "test", label: "Test" },
        { value: "quiz", label: "Kvíz" },
      ],
    },
    { key: "exam_date", label: "Termín", type: "date", required: true },
  ],
  assignment: [
    { key: "title", label: "Název", type: "text", required: true },
    { key: "subject_id", label: "Předmět", type: "subject", required: true },
    { key: "due_date", label: "Termín", type: "date", required: true },
    {
      key: "priority",
      label: "Priorita",
      type: "select",
      options: [
        { value: "low", label: "Nízká" },
        { value: "medium", label: "Střední" },
        { value: "high", label: "Vysoká" },
      ],
    },
  ],
};

export const QUICK_ADD_EXAMPLES: { kind: QuickAddKind; text: string }[] = [
  { kind: "reminder", text: "zítra fyzio v 17:00" },
  { kind: "reminder", text: "za 2 hodiny vyndat prádlo" },
  { kind: "finance", text: "oběd 189,90 Kč" },
  { kind: "finance", text: "příjem Servind 5000 Kč" },
  { kind: "work", text: "6,5 h Workshop za 375 Kč/h" },
  { kind: "exam", text: "test z práva 18. 10." },
  { kind: "assignment", text: "úkol algoritmizace do pátku" },
];

export function isQuickAddKind(kind: unknown): kind is QuickAddKind {
  return typeof kind === "string" && (QUICK_ADD_KINDS as string[]).includes(kind);
}

/** Ctrl/⌘ + Shift + K. Ctrl+K (bez Shiftu) zůstává globálnímu vyhledávání. */
export function isQuickAddShortcut(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean }): boolean {
  return (e.ctrlKey || e.metaKey) && e.shiftKey && !e.altKey && (e.key === "k" || e.key === "K");
}

export type FormValues = Record<string, string | boolean>;

/** Pole z parseru → hodnoty formuláře (vše řetězce kromě checkboxu). */
export function fieldsToForm(kind: QuickAddKind, fields: Record<string, unknown>): FormValues {
  const out: FormValues = {};
  for (const def of FIELD_DEFS[kind]) {
    const v = fields[def.key];
    if (def.type === "checkbox") out[def.key] = v === undefined ? true : Boolean(v);
    else if (v === null || v === undefined) out[def.key] = "";
    else if (def.type === "number") out[def.key] = String(v).replace(".", ",");
    else out[def.key] = String(v);
  }
  return out;
}

/** „189,90" / „1 250" → 189.9 / 1250; prázdné / nesmysl → null. */
export function parseCzNumber(raw: string): number | null {
  const s = raw.replace(/[\s ]/g, "").replace(",", ".");
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Hodnoty formuláře → pole pro /quick-add/prepare (server je stejně znovu ověří). */
export function formToFields(kind: QuickAddKind, form: FormValues): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const def of FIELD_DEFS[kind]) {
    const v = form[def.key];
    if (def.type === "checkbox") out[def.key] = Boolean(v);
    else if (def.type === "number") out[def.key] = parseCzNumber(String(v ?? ""));
    else if (def.type === "subject") out[def.key] = v ? Number(v) : null;
    else out[def.key] = String(v ?? "").trim();
  }
  return out;
}

/** Chyba parseru „date" u školy patří k poli termínu. */
export function issueField(kind: QuickAddKind, field: string): string {
  if (field === "date" && kind === "exam") return "exam_date";
  if (field === "date" && kind === "assignment") return "due_date";
  if (field === "time" && kind === "reminder") return "due_local";
  return field;
}

export interface ReadinessInput {
  kind: QuickAddKind;
  form: FormValues;
  questions: QuickAddQuestion[];
  /** pole, která uživatel upravil nebo výslovně potvrdil */
  resolved: ReadonlySet<string>;
  errors: QuickAddIssue[];
}

export interface Readiness {
  ready: boolean;
  /** důvody, proč ještě nejde uložit (česky, pro nápovědu u tlačítka) */
  blockers: string[];
  openQuestions: QuickAddQuestion[];
  fieldErrors: Record<string, string>;
}

/**
 * Lze uložit? Povinná pole vyplněná, každá otázka parseru vyřešená (pole upravené nebo hodnota potvrzená)
 * a žádná chyba na poli, které uživatel od rozboru neupravil.
 */
export function readiness({ kind, form, questions, resolved, errors }: ReadinessInput): Readiness {
  const blockers: string[] = [];
  const fieldErrors: Record<string, string> = {};
  for (const e of errors) {
    const f = issueField(kind, e.field);
    if (!resolved.has(f) && !fieldErrors[f]) fieldErrors[f] = e.message;
  }
  const openQuestions = questions.filter((q) => !resolved.has(q.field));
  const missing = FIELD_DEFS[kind].filter((d) => d.required && d.type !== "checkbox" && !String(form[d.key] ?? "").trim());
  for (const d of missing) blockers.push(`Doplň: ${d.label.toLowerCase()}.`);
  for (const d of FIELD_DEFS[kind]) {
    if (d.type === "number" && String(form[d.key] ?? "").trim() && parseCzNumber(String(form[d.key])) === null) {
      fieldErrors[d.key] = fieldErrors[d.key] ?? "Musí to být číslo.";
    }
  }
  if (openQuestions.length) blockers.push(openQuestions[0].question);
  const errorList = Object.values(fieldErrors);
  if (errorList.length) blockers.push(errorList[0]);
  return { ready: blockers.length === 0, blockers, openQuestions, fieldErrors };
}

/** Odpověď 422 z /quick-add/prepare: {detail: {errors: [{field, message}]}}. */
export function prepareErrors(body: unknown): QuickAddIssue[] {
  const detail = isRecord(body) ? body.detail : null;
  const errors = isRecord(detail) ? detail.errors : null;
  if (!Array.isArray(errors)) return [];
  return errors
    .filter(isRecord)
    .map((e) => ({ field: String(e.field ?? ""), message: String(e.message ?? "") }))
    .filter((e) => e.message);
}

/** Bezpečné převzetí odpovědi /quick-add/parse (neznámý tvar → „unknown"). */
export function normalizeParse(raw: unknown): QuickAddParse {
  const r = isRecord(raw) ? raw : {};
  const kind = isQuickAddKind(r.kind) || r.kind === "empty" ? (r.kind as ParsedKind) : "unknown";
  const confidence = r.confidence === "high" || r.confidence === "medium" ? r.confidence : "low";
  const display = isRecord(r.display) ? r.display : {};
  return {
    kind,
    confidence,
    fields: isRecord(r.fields) ? r.fields : {},
    display: {
      title: String(display.title ?? ""),
      subtitle: String(display.subtitle ?? ""),
      area: typeof display.area === "string" ? display.area : null,
    },
    warnings: Array.isArray(r.warnings) ? r.warnings.map(String) : [],
    needs_input: Array.isArray(r.needs_input)
      ? r.needs_input.filter(isRecord).map((q) => ({ field: String(q.field ?? ""), question: String(q.question ?? "") }))
      : [],
    errors: Array.isArray(r.errors)
      ? r.errors.filter(isRecord).map((e) => ({ field: String(e.field ?? ""), message: String(e.message ?? "") }))
      : [],
    ready: r.ready === true,
    subjects: Array.isArray(r.subjects)
      ? r.subjects.filter(isRecord).map((s) => ({ id: Number(s.id), name: String(s.name ?? "") }))
      : undefined,
  };
}

/** Otázka, kterou jde vyřešit jedním „Ano" (parser už hodnotu navrhl, jen si není jistý – „Je to 820 Kč?"). */
export function canAcknowledge(q: QuickAddQuestion, form: FormValues): boolean {
  return q.question.endsWith("?") && String(form[q.field] ?? "").trim() !== "" && q.field === "amount";
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
