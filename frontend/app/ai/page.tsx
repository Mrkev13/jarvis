"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, apiFetch } from "@/lib/api";
import { MOTION } from "@/lib/motion";
import {
  confirmActionBody,
  normalizePendingActions,
  rejectActionPath,
  type PendingAction,
} from "@/lib/pendingActions";
import PlannerCardRenderer, { type PlannerCard } from "@/components/PlannerCards";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";
import {
  detectSpeechLocaleFromText,
  getStoredTtsEnabled,
  isSpeechSynthesisSupported,
  plannerSpeechSummary,
  setStoredTtsEnabled,
  speakText,
  SUPPORTED_LOCALES,
  type SpeechLocale,
  type SpeechPlannerCard,
  type TtsHandle,
} from "@/lib/speech";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: number;
  plannerCard?: PlannerCard | null;
};

type ActionOutcome = {
  key: string;
  title: string;
  kind: "success" | "rejected";
};

type ConversationItem = {
  id: number;
  title: string;
  createdAt: number;
  updatedAt: number;
};

function formatConversationUpdatedAt(ts: number): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function toTs(value: unknown): number {
  if (!value) return Date.now();
  if (typeof value === "number") return value;
  if (typeof value === "string") {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) return d.getTime();
    return Date.now();
  }
  if (value instanceof Date) return value.getTime();
  return Date.now();
}

type PlannerAction = {
  priority: number;
  area: string;
  title: string;
  reason: string;
};

type WeeklyPlan = {
  summary: string;
  actions: PlannerAction[];
};

const currencyFmt = new Intl.NumberFormat("cs-CZ", {
  style: "currency",
  currency: "CZK",
  maximumFractionDigits: 2,
});

const dateFmt = new Intl.DateTimeFormat("cs-CZ", {
  day: "numeric",
  month: "numeric",
  year: "numeric",
});

const numberFmt = new Intl.NumberFormat("cs-CZ", {
  maximumFractionDigits: 2,
});

function formatIsoDate(iso: string | undefined | null): string {
  if (!iso) return "–";
  try {
    return dateFmt.format(new Date(`${iso}T00:00:00`));
  } catch {
    return iso;
  }
}

function describeWorkSession(args: Record<string, unknown>) {
  const date_value = (args.date_value as string) ?? "";
  const hours = Number(args.hours) || 0;
  const project = (args.project as string) ?? "";
  const hourly_rate = Number(args.hourly_rate) || 0;
  const description = (args.description as string) ?? "";
  const earnings = hours * hourly_rate;

  return {
    title: "Přidat pracovní session",
    fields: [
      { label: "Datum", value: formatIsoDate(date_value) },
      { label: "Projekt", value: project || "–" },
      { label: "Hodiny", value: numberFmt.format(hours) },
      {
        label: "Sazba",
        value: `${numberFmt.format(hourly_rate)} Kč/h`,
      },
      ...(description ? [{ label: "Poznámka", value: description }] : []),
    ],
    footer: {
      label: "Výdělek",
      value: currencyFmt.format(earnings),
    },
    detailLines: [
      formatIsoDate(date_value),
      project || "–",
      `${numberFmt.format(hours)} h`,
      `${numberFmt.format(hourly_rate)} Kč/h`,
      currencyFmt.format(earnings),
    ],
  };
}

function describeFinanceTransaction(args: Record<string, unknown>) {
  const amount = Number(args.amount) || 0;
  const category = (args.category as string) ?? "";
  const type = (args.transaction_type as string) ?? "expense";
  const description = (args.description as string) ?? "";
  const isIncome = type === "income";

  return {
    title: isIncome ? "Přidat příjem" : "Přidat výdaj",
    fields: [
      {
        label: "Částka",
        value: (isIncome ? "+ " : "− ") + currencyFmt.format(amount),
      },
      { label: "Kategorie", value: category || "Ostatní" },
      { label: "Typ", value: isIncome ? "Příjem" : "Výdaj" },
      ...(description ? [{ label: "Popis", value: description }] : []),
    ],
    footer: {
      label: isIncome ? "Celkový příjem" : "Celkový výdaj",
      value: currencyFmt.format(amount),
    },
    detailLines: [
      (isIncome ? "Příjem" : "Výdaj"),
      `${currencyFmt.format(amount)}`,
      `Kategorie: ${category || "Ostatní"}`,
      ...(description ? [description] : []),
    ],
  };
}

function describeSchoolSubject(args: Record<string, unknown>) {
  const name = (args.name as string) ?? "";
  const code = (args.code as string) ?? "";
  const semester = (args.semester as string) ?? "";
  const credits = Number(args.credits) || 0;
  const active = args.active === undefined ? true : Boolean(args.active);

  return {
    title: "Přidat školní předmět",
    fields: [
      { label: "Název", value: name || "–" },
      ...(code ? [{ label: "Zkratka", value: code }] : []),
      ...(semester ? [{ label: "Semestr", value: semester }] : []),
      { label: "ECTS kredity", value: String(credits) },
      { label: "Aktivní", value: active ? "Ano" : "Ne" },
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      name,
      ...(code ? [code] : []),
      ...(semester ? [semester] : []),
      `${credits} ECTS`,
    ],
  };
}

function describeSchoolAssignment(args: Record<string, unknown>) {
  const title = (args.title as string) ?? "";
  const subject_id = args.subject_id ?? "–";
  const description = (args.description as string) ?? "";
  const due_date = (args.due_date as string) ?? "";
  const priority = (args.priority as string) ?? "medium";
  const status = (args.status as string) ?? "todo";

  return {
    title: "Přidat úkol",
    fields: [
      { label: "Název", value: title || "–" },
      { label: "Předmět ID", value: String(subject_id) },
      ...(due_date ? [{ label: "Odevzdat do", value: formatIsoDate(due_date) }] : []),
      { label: "Priorita", value: priority.toUpperCase() },
      { label: "Status", value: status },
      ...(description ? [{ label: "Popis", value: description }] : []),
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      title,
      ...(due_date ? [`Do: ${formatIsoDate(due_date)}`] : []),
      `Priorita: ${priority.toUpperCase()}`,
    ],
  };
}

function describeSchoolExam(args: Record<string, unknown>) {
  const title = (args.title as string) ?? "";
  const subject_id = args.subject_id ?? "–";
  const exam_type = (args.exam_type as string) ?? "exam";
  const exam_date = (args.exam_date as string) ?? "";
  const status = (args.status as string) ?? "upcoming";
  const notes = (args.notes as string) ?? "";

  const typeMap: Record<string, string> = {
    exam: "Zkouška",
    test: "Písemka",
    quiz: "Kvíz",
    paper: "Zápočet",
    other: "Jiné",
  };
  return {
    title: "Přidat zkoušku",
    fields: [
      { label: "Název", value: title || "–" },
      { label: "Předmět ID", value: String(subject_id) },
      { label: "Druh", value: typeMap[exam_type] ?? exam_type },
      ...(exam_date ? [{ label: "Datum", value: formatIsoDate(exam_date) }] : []),
      { label: "Status", value: status },
      ...(notes ? [{ label: "Poznámky", value: notes }] : []),
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      title,
      `${typeMap[exam_type] ?? exam_type}${exam_date ? ` — ${formatIsoDate(exam_date)}` : ""}`,
      `Status: ${status}`,
    ],
  };
}

function describeWotResource(args: Record<string, unknown>) {
  const resource = (args.resource as string) ?? "";
  const amount = Number(args.amount) || 0;

  const labelMap: Record<string, string> = {
    credits: "Credits",
    gold: "Gold",
    bonds: "Bonds",
    free_xp: "Free XP",
  };
  return {
    title: "Aktualizovat WoT surovinu",
    fields: [
      { label: "Surovina", value: labelMap[resource] ?? resource ?? "–" },
      {
        label: "Aktuální množství",
        value: numberFmt.format(amount),
      },
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      `${labelMap[resource] ?? resource}: ${numberFmt.format(amount)}`,
    ],
  };
}

function describeWotGrind(args: Record<string, unknown>) {
  const tank = (args.tank as string) ?? "";
  const xp_remaining = Number(args.xp_remaining) || 0;
  const priority = (args.priority as string) ?? "medium";
  const status = (args.status as string) ?? "active";

  return {
    title: "Upsert WoT grind",
    fields: [
      { label: "Tank", value: tank || "–" },
      { label: "Zbývá XP", value: numberFmt.format(xp_remaining) },
      { label: "Priorita", value: priority.toUpperCase() },
      { label: "Status", value: status },
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      tank,
      `Zbývá: ${numberFmt.format(xp_remaining)} XP`,
      `Priorita: ${priority.toUpperCase()} • Status: ${status}`,
    ],
  };
}

function describeMffCharacter(args: Record<string, unknown>) {
  const name = (args.name as string) ?? "";
  const tier = (args.tier as string) ?? "T3";
  const level = Number(args.level) || 0;
  const uniform = (args.uniform as string) ?? "";
  const ctp = (args.ctp as string) ?? "";
  const artifact = (args.artifact as string) ?? "";
  const role = (args.role as string) ?? "";
  const team = (args.team as string) ?? "";
  const uru_state = (args.uru_state as string) ?? "";
  const iso8_set = (args.iso8_set as string) ?? "";
  const build_completeness = Math.max(
    0,
    Math.min(100, Number(args.build_completeness) || 0),
  );
  const priority = (args.priority as string) ?? "medium";
  const status = (args.status as string) ?? "built";
  const notes = (args.notes as string) ?? "";

  return {
    title: "Upsert MFF postavu",
    fields: [
      { label: "Jméno", value: name || "–" },
      { label: "Tier", value: tier },
      { label: "Level", value: String(level) },
      ...(uniform ? [{ label: "Uniform", value: uniform }] : []),
      ...(ctp ? [{ label: "CTP", value: ctp }] : []),
      ...(artifact ? [{ label: "Artifact", value: artifact }] : []),
      ...(role ? [{ label: "Role", value: role }] : []),
      ...(team ? [{ label: "Team", value: team }] : []),
      ...(uru_state ? [{ label: "Uru", value: uru_state }] : []),
      ...(iso8_set ? [{ label: "ISO-8", value: iso8_set }] : []),
      { label: "Build %", value: `${build_completeness} %` },
      { label: "Priorita", value: priority.toUpperCase() },
      { label: "Status", value: status },
      ...(notes ? [{ label: "Poznámky", value: notes }] : []),
    ],
    footer: null as { label: string; value: string } | null,
    detailLines: [
      `${name} (${tier} Lv.${level})`,
      `Build: ${build_completeness} % • Priorita: ${priority.toUpperCase()} • Status: ${status}`,
      ...(uniform ? [`Uniform: ${uniform}`] : []),
    ],
  };
}

function describeGoal(args: Record<string, unknown>) {
  const area = (args.area as string) ?? "";
  const title = (args.title as string) ?? "";
  const id = args.id;
  const description = (args.description as string) ?? "";
  const status = (args.status as string) ?? "active";
  const priority = (args.priority as string) ?? "medium";
  const progress = Math.max(0, Math.min(100, Number(args.progress) || 0));
  const target_date = (args.target_date as string) ?? "";

  const areaName: Record<string, string> = {
    finance: "Finance",
    school: "Škola",
    work: "Práce",
    wot: "World of Tanks",
    mff: "Marvel Future Fight",
    personal: "Osobní",
    travel: "Cestování",
    fitness: "Fitness",
    hobby: "Hobby",
  };

  return {
    title: id ? "Aktualizovat cíl" : "Přidat cíl",
    fields: [
      ...(id ? [{ label: "Cíl ID", value: String(id) }] : []),
      { label: "Oblast", value: areaName[area] ?? area ?? "–" },
      { label: "Titulek", value: title || "–" },
      { label: "Status", value: status },
      { label: "Priorita", value: priority.toUpperCase() },
      { label: "Pokrok", value: `${progress} %` },
      ...(target_date
        ? [{ label: "Cílové datum", value: formatIsoDate(target_date) }]
        : []),
      ...(description ? [{ label: "Popis", value: description }] : []),
    ],
    footer: {
      label: "Pokrok",
      value: `${progress} %`,
    },
    detailLines: [
      title,
      `${areaName[area] ?? area} • Priorita: ${priority.toUpperCase()}`,
      `Pokrok: ${progress} %${target_date ? ` • Cíl: ${formatIsoDate(target_date)}` : ""}`,
    ],
  };
}

function describeMemory(args: Record<string, unknown>) {
  const area = (args.area as string) ?? "general";
  const category = (args.category as string) ?? "context";
  const content = (args.content as string) ?? "";
  const importance = Math.max(1, Math.min(10, Number(args.importance) || 5));
  const active = args.active === undefined ? true : Boolean(args.active);

  const areaMap: Record<string, string> = {
    general: "Obecné",
    wot: "World of Tanks",
    finance: "Finance",
    school: "Škola",
    work: "Práce",
    mff: "Marvel Future Fight",
    personal: "Osobní",
    fitness: "Fitness",
    hobby: "Hobby",
    travel: "Cestování",
  };

  const catMap: Record<string, string> = {
    preference: "Preference",
    decision: "Rozhodnutí",
    context: "Kontext",
    routine: "Rutina",
    constraint: "Omezení",
    plan: "Plán",
  };

  const importanceBars = "★".repeat(importance) + "☆".repeat(10 - importance);

  return {
    title: "Uložit paměť",
    fields: [
      { label: "Oblast", value: areaMap[area] ?? area },
      { label: "Kategorie", value: catMap[category] ?? category },
      { label: "Obsah", value: content || "–" },
      { label: "Důležitost", value: `${importanceBars} (${importance}/10)` },
      { label: "Aktivní", value: active ? "Ano" : "Ne" },
    ],
    footer: {
      label: "Důležitost",
      value: `${importance}/10`,
    },
    detailLines: [
      `${areaMap[area] ?? area} • ${catMap[category] ?? category}`,
      content || "–",
      `Důležitost: ${importance}/10`,
    ],
  };
}

function describePendingAction(action: PendingAction) {
  switch (action.tool) {
    case "add_work_session":
      return describeWorkSession(action.arguments);
    case "add_finance_transaction":
      return describeFinanceTransaction(action.arguments);
    case "add_school_subject":
      return describeSchoolSubject(action.arguments);
    case "add_school_assignment":
      return describeSchoolAssignment(action.arguments);
    case "add_school_exam":
      return describeSchoolExam(action.arguments);
    case "update_wot_resource":
      return describeWotResource(action.arguments);
    case "upsert_wot_grind":
      return describeWotGrind(action.arguments);
    case "upsert_mff_character":
      return describeMffCharacter(action.arguments);
    case "upsert_goal":
      return describeGoal(action.arguments);
    case "save_memory":
      return describeMemory(action.arguments);
    default:
      return {
        title: `${action.tool}`,
        fields: Object.entries(action.arguments).map(([k, v]) => ({
          label: k,
          value: typeof v === "string" ? v : JSON.stringify(v),
        })),
        footer: null as { label: string; value: string } | null,
        detailLines: [`${action.tool}`],
      };
  }
}

function formatInline(text: string) {
  let out = text;
  out = out.replace(/`([^`]+)`/g, "@@@CODE@@@$1@@@ENDCODE@@@");
  out = out.replace(/\*\*([^*]+)\*\*/g, "@@@B@@@$1@@@ENDB@@@");
  out = out.replace(/\*([^*]+)\*/g, "@@@I@@@$1@@@ENDI@@@");
  out = out.replace(/_([^_]+)_/g, "@@@I@@@$1@@@ENDI@@@");
  return out;
}

function renderInline(run: string) {
  const parts: React.ReactNode[] = [];
  let key = 0;
  const tokens = run.split(
    /(@@@CODE@@@.*?@@@ENDCODE@@@|@@@B@@@.*?@@@ENDB@@@|@@@I@@@.*?@@@ENDI@@@)/,
  );
  for (const tok of tokens) {
    if (!tok) continue;
    if (tok.startsWith("@@@CODE@@@") && tok.endsWith("@@@ENDCODE@@@")) {
      const inner = tok.slice(10, -12);
      parts.push(
        <code
          key={`c-${key++}`}
          className="px-1.5 py-0.5 bg-zinc-900 border border-zinc-700 rounded text-[0.85em] text-amber-300"
        >
          {inner}
        </code>,
      );
    } else if (tok.startsWith("@@@B@@@") && tok.endsWith("@@@ENDB@@@")) {
      const inner = tok.slice(7, -10);
      parts.push(
        <strong key={`b-${key++}`} className="font-semibold">
          {renderInline(inner)}
        </strong>,
      );
    } else if (tok.startsWith("@@@I@@@") && tok.endsWith("@@@ENDI@@@")) {
      const inner = tok.slice(7, -10);
      parts.push(
        <em key={`i-${key++}`} className="italic">
          {renderInline(inner)}
        </em>,
      );
    } else {
      parts.push(tok);
    }
  }
  return parts;
}

function tryParseWeeklyPlan(buf: string[]): WeeklyPlan | null {
  try {
    const raw = buf.join("\n");
    const parsed = JSON.parse(raw) as Partial<WeeklyPlan>;
    if (!parsed || typeof parsed !== "object") return null;
    if (typeof parsed.summary !== "string") return null;
    if (!Array.isArray(parsed.actions)) return null;
    if (parsed.actions.length === 0 || parsed.actions.length > 8) return null;
    for (const a of parsed.actions) {
      const act = a as Partial<PlannerAction>;
      if (typeof act?.priority !== "number") return null;
      if (typeof act.area !== "string") return null;
      if (typeof act.title !== "string") return null;
      if (typeof act.reason !== "string") return null;
    }
    return parsed as WeeklyPlan;
  } catch {
    return null;
  }
}

const AREA_STYLES: Record<string, { bg: string; border: string; text: string; label: string }> = {
  school:   { bg: "bg-blue-500/10",    border: "border-blue-400/30",    text: "text-blue-300",    label: "Škola" },
  work:     { bg: "bg-purple-500/10",  border: "border-purple-400/30",  text: "text-purple-300",  label: "Práce" },
  finance:  { bg: "bg-emerald-500/10", border: "border-emerald-400/30", text: "text-emerald-300", label: "Finance" },
  wot:      { bg: "bg-amber-500/10",   border: "border-amber-400/30",   text: "text-amber-300",   label: "World of Tanks" },
  mff:      { bg: "bg-indigo-500/10",  border: "border-indigo-400/30",  text: "text-indigo-300",  label: "Marvel FF" },
  personal: { bg: "bg-pink-500/10",    border: "border-pink-400/30",    text: "text-pink-300",    label: "Osobní" },
  fitness:  { bg: "bg-green-500/10",   border: "border-green-400/30",   text: "text-green-300",   label: "Fitness" },
  hobby:    { bg: "bg-orange-500/10",  border: "border-orange-400/30",  text: "text-orange-300",  label: "Hobby" },
  travel:   { bg: "bg-teal-500/10",    border: "border-teal-400/30",    text: "text-teal-300",    label: "Cestování" },
  general:  { bg: "bg-zinc-500/10",    border: "border-zinc-400/30",    text: "text-zinc-300",    label: "Obecné" },
};

function areaMeta(area: string) {
  return (
    AREA_STYLES[area?.toLowerCase?.()] ?? {
      bg: "bg-zinc-500/10",
      border: "border-zinc-400/30",
      text: "text-zinc-300",
      label: area ?? "Obecné",
    }
  );
}

function WeeklyPlanCard({ plan }: { plan: WeeklyPlan }) {
  const sorted = [...plan.actions].sort((a, b) => a.priority - b.priority);

  return (
    <div className="my-4 rounded-2xl border border-zinc-700 bg-gradient-to-br from-zinc-900 via-zinc-900 to-zinc-950 overflow-hidden shadow-lg">
      <div className="px-5 py-4 bg-gradient-to-r from-indigo-600/30 via-violet-600/20 to-fuchsia-600/20 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/10 grid place-items-center text-lg">
            📅
          </div>
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-[0.18em] text-indigo-200/70 font-semibold">
              Weekly plan
            </div>
            <div className="mt-0.5 text-zinc-100 font-semibold leading-snug">
              {plan.summary}
            </div>
          </div>
        </div>
      </div>

      <div className="px-4 py-3 space-y-2.5">
        {sorted.map((action, idx) => {
          const meta = areaMeta(action.area);
          const isTop = idx === 0;
          const priority = Number.isFinite(action.priority) ? action.priority : idx + 1;
          return (
            <div
              key={idx}
              className={
                "group rounded-xl border p-3.5 transition-all " +
                meta.border +
                " " +
                meta.bg +
                (isTop ? " ring-1 ring-amber-400/30" : "")
              }
            >
              <div className="flex items-start gap-3">
                <div
                  className={
                    "shrink-0 w-9 h-9 rounded-full grid place-items-center font-bold text-sm border " +
                    (isTop
                      ? "bg-amber-400/90 text-zinc-950 border-amber-300"
                      : "bg-white/5 text-zinc-100 border-white/10")
                  }
                >
                  {priority}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span
                      className={
                        "inline-flex items-center px-2 py-0.5 rounded-md text-[11px] uppercase tracking-wider font-semibold border " +
                        meta.bg +
                        " " +
                        meta.border +
                        " " +
                        meta.text
                      }
                    >
                      {meta.label}
                    </span>
                    {isTop && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold bg-amber-400/10 text-amber-300 border border-amber-400/25">
                        🔥 Nejvyšší priorita
                      </span>
                    )}
                  </div>
                  <div className="text-zinc-100 font-semibold leading-snug">
                    {action.title}
                  </div>
                  {action.reason && (
                    <div className="mt-1 text-sm text-zinc-400 leading-snug">
                      <span className="text-zinc-500 mr-1">Důvod:</span>
                      {action.reason}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatMarkdown(content: string): React.ReactNode[] {
  const lines = content.split(/\r?\n/);
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let k = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) {
      i++;
      continue;
    }

    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;

      if (lang === "json" || !lang) {
        const plan = tryParseWeeklyPlan(buf);
        if (plan) {
          blocks.push(<WeeklyPlanCard key={`plan-${k++}`} plan={plan} />);
          continue;
        }
      }

      blocks.push(
        <pre
          key={`p-${k++}`}
          className="my-3 bg-zinc-950 border border-zinc-800 rounded-xl p-4 overflow-x-auto text-sm"
        >
          {lang && (
            <div className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
              {lang}
            </div>
          )}
          <code className="text-amber-200 whitespace-pre-wrap">
            {buf.join("\n")}
          </code>
        </pre>,
      );
      continue;
    }

    const h2 = line.match(/^##\s+(.+)$/);
    if (h2) {
      blocks.push(
        <h3
          key={`h2-${k++}`}
          className="mt-5 mb-2 text-lg font-bold text-white leading-snug first:mt-1"
        >
          {renderInline(formatInline(h2[1]))}
        </h3>,
      );
      i++;
      continue;
    }

    const h3 = line.match(/^###\s+(.+)$/);
    if (h3) {
      blocks.push(
        <h4
          key={`h3-${k++}`}
          className="mt-4 mb-2 text-base font-semibold text-white leading-snug"
        >
          {renderInline(formatInline(h3[1]))}
        </h4>,
      );
      i++;
      continue;
    }

    const h1 = line.match(/^#\s+(.+)$/);
    if (h1) {
      blocks.push(
        <h2
          key={`h1-${k++}`}
          className="mt-5 mb-2 text-xl font-bold text-white leading-snug first:mt-1"
        >
          {renderInline(formatInline(h1[1]))}
        </h2>,
      );
      i++;
      continue;
    }

    const olMatch = line.match(/^\s*\d+\.\s+(.+)$/);
    if (olMatch) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+(.+)$/.test(lines[i])) {
        const m = lines[i].match(/^\s*\d+\.\s+(.+)$/);
        if (m) items.push(m[1]);
        i++;
      }
      blocks.push(
        <ol
          key={`ol-${k++}`}
          className="my-2 ml-5 list-decimal space-y-1 marker:text-zinc-500"
        >
          {items.map((it, idx) => (
            <li key={idx} className="leading-7">
              {renderInline(formatInline(it))}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    const ulMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (ulMatch) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+(.+)$/.test(lines[i])) {
        const m = lines[i].match(/^\s*[-*]\s+(.+)$/);
        if (m) items.push(m[1]);
        i++;
      }
      blocks.push(
        <ul
          key={`ul-${k++}`}
          className="my-2 ml-5 list-disc space-y-1 marker:text-zinc-500"
        >
          {items.map((it, idx) => (
            <li key={idx} className="leading-7">
              {renderInline(formatInline(it))}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    const buf: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^#/.test(lines[i]) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^\s*\d+\.\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith("```")
    ) {
      buf.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={`par-${k++}`} className="my-2 leading-8 text-zinc-200">
        {renderInline(formatInline(buf.join(" ")))}
      </p>,
    );
  }

  return blocks;
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1.5 py-1 text-zinc-400">
      <span
        className="inline-block h-2 w-2 rounded-full bg-zinc-400 animate-bounce"
        style={{ animationDelay: "0ms" }}
      />
      <span
        className="inline-block h-2 w-2 rounded-full bg-zinc-400 animate-bounce"
        style={{ animationDelay: "120ms" }}
      />
      <span
        className="inline-block h-2 w-2 rounded-full bg-zinc-400 animate-bounce"
        style={{ animationDelay: "240ms" }}
      />
      <span className="ml-2 text-xs text-zinc-500">Standa AI přemýšlí…</span>
    </div>
  );
}

export default function AiPage() {
  const [message, setMessage] = useState("");
  const [history, setHistory] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([]);
  const [confirmingIdx, setConfirmingIdx] = useState<number | null>(null);
  // UI-only stavy pending akcí (logika potvrzení se nemění):
  // failed = akce, jejíž potvrzení selhalo (zůstává v seznamu) – červený stav + zatřesení,
  // outcomes = krátké dočasné karty „potvrzeno / zrušeno" po odebrání akce ze seznamu.
  const [failedAction, setFailedAction] = useState<{ action: PendingAction; attempt: number } | null>(null);
  const [actionOutcomes, setActionOutcomes] = useState<ActionOutcome[]>([]);
  const outcomeSeq = useRef(0);

  function showActionOutcome(title: string, kind: ActionOutcome["kind"]) {
    outcomeSeq.current += 1;
    const key = `${kind}-${outcomeSeq.current}`;
    setActionOutcomes((prev) => [...prev, { key, title, kind }]);
    window.setTimeout(() => {
      setActionOutcomes((prev) => prev.filter((o) => o.key !== key));
    }, MOTION.highlightMs);
  }

  function markActionFailed(action: PendingAction) {
    setFailedAction((prev) => ({
      action,
      attempt: prev && prev.action === action ? prev.attempt + 1 : 1,
    }));
  }
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(
    null,
  );
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [mobileChatsOpen, setMobileChatsOpen] = useState(false);
  const [ttsEnabled, setTtsEnabledState] = useState<boolean>(() => getStoredTtsEnabled(true));
  const [activeTtsKey, setActiveTtsKey] = useState<string | null>(null);
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setIsClient(true);
    });
  }, []);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const ttsRef = useRef<TtsHandle | null>(null);
  const sendMessageRef = useRef<(() => Promise<void>) | null>(null);
  const autoSendRef = useRef<boolean>(false);
  const setMessageRef = useRef<React.Dispatch<React.SetStateAction<string>>>((s) => s);

  useEffect(() => {
    setMessageRef.current = setMessage;
  }, [setMessage]);

  const setTtsEnabled = useCallback((value: boolean) => {
    setTtsEnabledState(value);
    setStoredTtsEnabled(value);
    if (!value) {
      ttsRef.current?.stop();
      ttsRef.current = null;
      setActiveTtsKey(null);
    }
  }, []);

  const stopTts = useCallback(() => {
    ttsRef.current?.stop();
    ttsRef.current = null;
    setActiveTtsKey(null);
  }, []);

  const playText = useCallback(
    (key: string, text: string, preferredLocale: SpeechLocale) => {
      stopTts();
      if (!text || !ttsEnabled || !isSpeechSynthesisSupported()) return;
      const locale = detectSpeechLocaleFromText(text) || preferredLocale;
      const handle = speakText(text, locale);
      ttsRef.current = handle;
      setActiveTtsKey(key);
      const checkInterval = window.setInterval(() => {
        if (!handle.isSpeaking()) {
          window.clearInterval(checkInterval);
          if (ttsRef.current === handle) {
            ttsRef.current = null;
            setActiveTtsKey((cur) => (cur === key ? null : cur));
          }
        }
      }, 200);
    },
    [stopTts, ttsEnabled],
  );

  const onFinalTranscript = useCallback((text: string) => {
    if (!text) return;
    if (autoSendRef.current) {
      setMessageRef.current(text);
      queueMicrotask(() => {
        sendMessageRef.current?.();
      });
    } else {
      setMessageRef.current((prev) => (prev ? `${prev} ${text}` : text));
    }
  }, []);

  const {
    supported: speechSupported,
    status: speechStatus,
    transcript: speechTranscript,
    interim: speechInterim,
    error: speechError,
    locale: speechLocale,
    autoSend: speechAutoSend,
    setLocale: setSpeechLocale,
    setAutoSend: setSpeechAutoSend,
    start: startSpeech,
    stop: stopSpeech,
    resetTranscript: resetSpeechTranscript,
  } = useSpeechRecognition({ onFinalTranscript });

  const ttsSupported = isClient && isSpeechSynthesisSupported();
  const sttSupported = isClient && speechSupported;

  useEffect(() => {
    autoSendRef.current = speechAutoSend;
  }, [speechAutoSend]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history, loading, pendingActions]);

  function activeConversation() {
    const id = activeConversationId;
    if (id == null) return null;
    return conversations.find((c) => c.id === id) ?? null;
  }

  // keepPendingActions: obnova téže konverzace hned po /chat nesmí smazat právě
  // vrácené pending akce (jinak karta k potvrzení zmizí dřív, než ji lze potvrdit).
  const loadMessages = useCallback(async (conversationId: number, keepPendingActions = false) => {
    setLoadingMessages(true);
    try {
      const response = await apiFetch(`/conversations/${conversationId}/messages`);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = (await response.json()) as Array<{
        id: number;
        role: "user" | "assistant";
        content: string;
        created_at: string;
      }>;
      const mapped: Message[] = (data ?? []).map((m) => ({
        id: `db-${m.id}`,
        role: m.role,
        content: m.content,
        createdAt: toTs(m.created_at),
      }));
      setHistory(mapped);
      if (!keepPendingActions) {
        setPendingActions([]);
      }
    } finally {
      setLoadingMessages(false);
    }
  }, []);

  const createConversation = useCallback(async (title?: string): Promise<number | null> => {
    const response = await apiFetch("/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title ?? null }),
    });
    if (!response.ok) {
      return null;
    }
    const data = (await response.json()) as {
      id: number;
      title: string;
      created_at: string;
      updated_at: string;
    };
    const created: ConversationItem = {
      id: data.id,
      title: data.title,
      createdAt: toTs(data.created_at),
      updatedAt: toTs(data.updated_at),
    };
    setConversations((prev) => [created, ...prev]);
    setHistory([]);
    setPendingActions([]);
    setLoading(false);
    return created.id;
  }, []);

  const loadConversations = useCallback(async (preferId?: number, keepPendingActions = false) => {
    setLoadingConversations(true);
    try {
      const response = await apiFetch("/conversations");
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = (await response.json()) as Array<{
        id: number;
        title: string;
        created_at: string;
        updated_at: string;
      }>;
      const items: ConversationItem[] = (data ?? []).map((c) => ({
        id: c.id,
        title: c.title,
        createdAt: toTs(c.created_at),
        updatedAt: toTs(c.updated_at),
      }));
      setConversations(items);

      let nextId: number | null =
        preferId ?? activeConversationId ?? (items[0]?.id ?? null);
      if (!nextId) {
        nextId = await createConversation();
      }
      if (nextId !== null) {
        setActiveConversationId(nextId);
        await loadMessages(nextId, keepPendingActions);
      }
    } catch {
      return;
    } finally {
      setLoadingConversations(false);
    }
  }, [activeConversationId, createConversation, loadMessages]);

  async function renameConversation(conversationId: number) {
    const conv = conversations.find((c) => c.id === conversationId);
    const title = window.prompt("Název chatu", conv?.title ?? "Nový chat");
    if (title === null) return;
    const trimmed = title.trim();
    if (!trimmed) return;
    const response = await apiFetch(`/conversations/${conversationId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: trimmed }),
    });
    if (!response.ok) return;
    const data = (await response.json()) as {
      id: number;
      title: string;
      created_at: string;
      updated_at: string;
    };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === conversationId
          ? {
              ...c,
              title: data.title,
              updatedAt: toTs(data.updated_at),
            }
          : c,
      ),
    );
  }

  async function deleteConversation(conversationId: number) {
    const conv = conversations.find((c) => c.id === conversationId);
    const ok = window.confirm(
      `Opravdu smazat chat${conv?.title ? ` “${conv.title}”` : ""}?`,
    );
    if (!ok) return;
    const response = await apiFetch(`/conversations/${conversationId}`, {
      method: "DELETE",
    });
    if (!response.ok) return;
    setConversations((prev) => prev.filter((c) => c.id !== conversationId));
    if (activeConversationId === conversationId) {
      const next = conversations.find((c) => c.id !== conversationId)?.id ?? null;
      if (next) {
        setActiveConversationId(next);
        await loadMessages(next);
      } else {
        const created = await createConversation();
        if (created) {
          setActiveConversationId(created);
          await loadMessages(created);
        }
      }
    }
  }

  async function appendLocalAssistantMessageToDb(text: string) {
    const conversationId = activeConversationId;
    if (conversationId == null) return;
    try {
      await apiFetch(`/conversations/${conversationId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: "assistant", content: text }),
      });
    } catch {
      return;
    }
  }

  useEffect(() => {
    queueMicrotask(() => {
      void loadConversations();
    });
  }, [loadConversations]);

  async function confirmAction(idx: number) {
    const action = pendingActions[idx];
    if (!action) return;

    setConfirmingIdx(idx);
    try {
      const response = await apiFetch("/actions/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Backend vrací pending akci s `id`; /actions/confirm vyžaduje { action_id: <id> }.
        body: JSON.stringify(confirmActionBody(action)),
      });

      if (!response.ok) {
        let detail = "";
        try {
          const err = (await response.json()) as { detail?: unknown };
          detail = JSON.stringify(err.detail ?? err, null, 2);
        } catch {
          // ignore
        }
        throw new Error(
          `HTTP ${response.status}${detail ? ` — ${detail.slice(0, 400)}` : ""}`,
        );
      }

      const data = (await response.json()) as {
        ok: boolean;
        tool?: string;
        arguments?: Record<string, unknown>;
        result?: unknown;
        error?: string;
        detail?: string;
      };

      const info = describePendingAction(action);
      let botText: string;
      if (data.ok) {
        botText = `✅ ${info.title} byla uložena.\n\n${info.detailLines.join("\n")}`;
      } else {
        botText = `❌ Změnu se nepodařilo provést.\n\n${data.detail ?? data.error ?? "Neznámá chyba"}`;
      }

      setHistory((h) => [
        ...h,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: botText,
          createdAt: Date.now(),
        },
      ]);
      void appendLocalAssistantMessageToDb(botText);

      if (data.ok) {
        setPendingActions((prev) => prev.filter((_, i) => i !== idx));
        showActionOutcome(info.title, "success");
      } else {
        markActionFailed(action);
      }
    } catch (err) {
      console.error(err);
      markActionFailed(action);
      const msg =
        err instanceof Error
          ? `Chyba potvrzení: ${err.message}`
          : "Nepodařilo se potvrdit akci.";
      setHistory((h) => [
        ...h,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: msg,
          createdAt: Date.now(),
        },
      ]);
      void appendLocalAssistantMessageToDb(msg);
    } finally {
      setConfirmingIdx(null);
    }
  }

  async function cancelAction(idx: number) {
    const action = pendingActions[idx];
    setPendingActions((prev) => prev.filter((_, i) => i !== idx));
    const info = action ? describePendingAction(action) : null;
    showActionOutcome(info?.title ?? "Akce", "rejected");
    const botText = `❌ Akce byla zrušena${info ? `: ${info.title}` : ""}.`;
    setHistory((h) => [
      ...h,
      {
        id: `a-${Date.now()}`,
        role: "assistant",
        content: botText,
        createdAt: Date.now(),
      },
    ]);
    void appendLocalAssistantMessageToDb(botText);

    if (!action) return;
    // Zamítnout i na serveru (stejné id jako potvrzení) – jinak by pending akce zůstala
    // potvrditelná až do vypršení. 409 = už zpracovaná / vypršelá → není co rušit.
    try {
      const response = await apiFetch(rejectActionPath(action), { method: "POST" });
      if (!response.ok && response.status !== 409) {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.error(err);
      const warn =
        "⚠️ Zrušení se nepodařilo uložit na serveru – akce zůstane nepotvrzená a sama vyprší.";
      setHistory((h) => [
        ...h,
        { id: `a-${Date.now()}`, role: "assistant", content: warn, createdAt: Date.now() },
      ]);
      void appendLocalAssistantMessageToDb(warn);
    }
  }

  const sendMessage = useCallback(async () => {
    const prompt = message.trim();
    if (!prompt || loading) return;
    if (activeConversationId == null) return;

    try {
      stopSpeech();
    } catch {
      /* ignore */
    }
    try {
      resetSpeechTranscript();
    } catch {
      /* ignore */
    }

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: "user",
      content: prompt,
      createdAt: Date.now(),
    };

    const updatedHistory: Message[] = [...history, userMsg];

    setHistory(updatedHistory);
    setMessage("");
    setLoading(true);
    setPendingActions([]);

    try {
      let response: Response;
      try {
        response = await apiFetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            conversation_id: activeConversationId,
            message: prompt,
          }),
        });
      } catch (fetchErr) {
        const isNetwork =
          fetchErr instanceof TypeError &&
          (/Failed to fetch/i.test(fetchErr.message) ||
            /NetworkError/i.test(fetchErr.message) ||
            fetchErr.cause !== undefined);
        throw new Error(
          isNetwork
            ? `Network: Nepodařilo se připojit k backendu na ${API_URL}. Je backend spuštěný (run-backend.cmd)?`
            : `Načtení selhalo: ${fetchErr instanceof Error ? fetchErr.message : String(fetchErr)}`,
        );
      }

      let errBody: { error?: string; answer?: string } | null = null;
      try {
        errBody = (await response.clone().json()) as {
          error?: string;
          answer?: string;
        };
      } catch {
        errBody = null;
      }

      if (!response.ok) {
        const fallbackMsg =
          response.status === 429
            ? "AI má plnou kapacitu (Groq rate limit). Zkus to prosím za 10-20 sekund znovu."
            : response.status >= 500 && response.status < 600
              ? "AI backend má problém (5xx). Zkus to znovu, nebo restartuj backend."
              : `Server vrátil HTTP ${response.status}.`;
        const userMessage =
          (errBody && typeof errBody.answer === "string" && errBody.answer) ||
          (errBody && typeof errBody.error === "string"
            ? `⚠️ ${errBody.error}`
            : "") ||
          fallbackMsg;
        console.error("Chat request failed:", {
          status: response.status,
          body: errBody,
          conversationId: activeConversationId,
        });
        setHistory((h) => [
          ...h,
          {
            id: `a-${Date.now()}`,
            role: "assistant",
            content: userMessage,
            createdAt: Date.now(),
          },
        ]);
        void appendLocalAssistantMessageToDb(userMessage);
        setLoading(false);
        return;
      }

      const data = (await response.json()) as {
        answer: string;
        pending_actions?: unknown;
        planner_result?: PlannerCard | null;
      };

      const plannerCard: PlannerCard | null | undefined =
        data.planner_result &&
        (data.planner_result.card_type === "daily" ||
          data.planner_result.card_type === "weekly" ||
          data.planner_result.card_type === "goal_review")
          ? data.planner_result
          : null;

      setHistory((h) => [
        ...h,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: data.answer ?? "",
          createdAt: Date.now(),
          plannerCard,
        },
      ]);

      const incomingActions = normalizePendingActions(data.pending_actions);
      if (incomingActions.length > 0) {
        setPendingActions(incomingActions);
      }
      void loadConversations(activeConversationId ?? undefined, true);
    } catch (err) {
      console.error(err);
      const msg =
        err instanceof Error
          ? err.message.startsWith("Network:") || err.message.startsWith("Načtení selhalo:")
            ? err.message
            : `Chyba AI: ${err.message}`
          : "Nepodařilo se spojit s AI backendem.";
      setHistory((h) => [
        ...h,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: msg,
          createdAt: Date.now(),
        },
      ]);
      void appendLocalAssistantMessageToDb(msg);
    } finally {
      setLoading(false);
    }
  }, [
    message,
    loading,
    activeConversationId,
    stopSpeech,
    resetSpeechTranscript,
    history,
    appendLocalAssistantMessageToDb,
    loadConversations,
  ]);

  useEffect(() => {
    sendMessageRef.current = sendMessage;
  }, [sendMessage]);

  useEffect(() => {
    return () => {
      try {
        stopSpeech();
      } catch {
        /* ignore */
      }
      try {
        stopTts();
      } catch {
        /* ignore */
      }
    };
  }, [stopSpeech, stopTts]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && (e.key === "M" || e.key === "m")) {
        e.preventDefault();
        if (speechStatus === "listening" || speechStatus === "processing") {
          stopSpeech();
        } else if (speechSupported) {
          startSpeech();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [speechSupported, speechStatus, startSpeech, stopSpeech]);

  return (
    <main className="p-2 md:p-8 max-w-6xl mx-auto h-[calc(100vh-0px)] flex flex-col min-h-0">
      {mobileChatsOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileChatsOpen(false)}
        >
          <aside
            className="absolute left-0 top-0 h-full w-80 max-w-[88%] bg-zinc-950 border-r border-zinc-800 p-5 shadow-2xl animate-in slide-in-from-left"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold">Chaty</h2>
              <button
                type="button"
                aria-label="Zavřít"
                onClick={() => setMobileChatsOpen(false)}
                className="p-2 rounded-lg hover:bg-zinc-800 transition-colors text-xl leading-none"
              >
                ×
              </button>
            </div>
            <button
              type="button"
              disabled={loadingConversations}
              onClick={async () => {
                const id = await createConversation();
                if (id) {
                  setActiveConversationId(id);
                  await loadMessages(id);
                  setMobileChatsOpen(false);
                }
              }}
              className="w-full mb-4 bg-white text-black font-medium px-4 py-2.5 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
            >
              Nový chat
            </button>
            <div className="space-y-2">
              {conversations.map((c) => {
                const isActive = c.id === activeConversationId;
                return (
                  <div
                    key={c.id}
                    className={`flex items-center gap-2 rounded-xl border ${
                      isActive ? "border-indigo-500/40 bg-indigo-500/10" : "border-zinc-800 bg-zinc-900/40"
                    }`}
                  >
                    <button
                      type="button"
                      onClick={async () => {
                        setActiveConversationId(c.id);
                        await loadMessages(c.id);
                        setMobileChatsOpen(false);
                      }}
                      className="flex-1 text-left px-3 py-2.5 truncate"
                    >
                      <div className="truncate">{c.title}</div>
                      <div className="text-[11px] text-zinc-500 mt-0.5">
                        {formatConversationUpdatedAt(c.updatedAt)}
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => renameConversation(c.id)}
                      className="text-xs text-zinc-400 hover:text-zinc-200 px-2 py-2"
                    >
                      Přejm.
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteConversation(c.id)}
                      className="text-xs text-zinc-400 hover:text-zinc-200 px-2 py-2"
                    >
                      Smaz.
                    </button>
                  </div>
                );
              })}
            </div>
          </aside>
        </div>
      )}

      <header className="flex items-end justify-between mb-4 md:mb-6 gap-3">
        <div>
          <h1 className="text-2xl md:text-4xl font-bold">AI Assistant</h1>
          <p className="text-zinc-400 mt-1 md:mt-2 text-sm md:text-base">
            {activeConversation()?.title
              ? `Chat: ${activeConversation()?.title}`
              : "AI assistant napojený na tvoje data z WoT, Finance a School."}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button
            type="button"
            onClick={() => setMobileChatsOpen(true)}
            className="md:hidden text-xs text-zinc-300 hover:text-white px-3 py-2 rounded-xl border border-zinc-800 hover:border-zinc-700 transition-colors"
          >
            Chaty
          </button>
          <button
            type="button"
            disabled={loadingConversations}
            onClick={async () => {
              const id = await createConversation();
              if (id) {
                setActiveConversationId(id);
                await loadMessages(id);
              }
            }}
            className="text-xs bg-white text-black font-medium px-3 py-2 rounded-xl disabled:opacity-50 hover:bg-zinc-200 transition-colors"
          >
            Nový chat
          </button>
        </div>
      </header>

      <div className="flex-1 flex min-h-0 gap-4">
        <aside className="hidden md:flex w-80 bg-zinc-950 border border-zinc-800 rounded-2xl p-4 flex-col min-h-0">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs uppercase tracking-wider text-zinc-500 font-semibold">
              Chaty
            </div>
            <button
              type="button"
              disabled={loadingConversations}
              onClick={() => void loadConversations(activeConversationId ?? undefined)}
              className="text-xs text-zinc-400 hover:text-zinc-200"
            >
              Obnovit
            </button>
          </div>
          <div className="flex-1 overflow-y-auto space-y-2">
            {conversations.map((c) => {
              const isActive = c.id === activeConversationId;
              return (
                <div
                  key={c.id}
                  className={`group flex items-center gap-2 rounded-xl border ${
                    isActive ? "border-indigo-500/40 bg-indigo-500/10" : "border-zinc-800 bg-zinc-900/40"
                  }`}
                >
                  <button
                    type="button"
                    onClick={async () => {
                      setActiveConversationId(c.id);
                      await loadMessages(c.id);
                    }}
                    className="flex-1 text-left px-3 py-2.5 truncate"
                  >
                    <div className="truncate">{c.title}</div>
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      {formatConversationUpdatedAt(c.updatedAt)}
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => renameConversation(c.id)}
                    className="text-xs text-zinc-500 hover:text-zinc-200 px-2 py-2 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Přejm.
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteConversation(c.id)}
                    className="text-xs text-zinc-500 hover:text-zinc-200 px-2 py-2 opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Smaz.
                  </button>
                </div>
              );
            })}
            {loadingConversations && (
              <div className="text-sm text-zinc-500 px-2 py-3">Načítám…</div>
            )}
          </div>
        </aside>

        <section className="flex-1 bg-zinc-900 border border-zinc-800 rounded-2xl flex flex-col overflow-hidden min-h-0">
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-3 md:p-6 space-y-4 md:space-y-5"
          >
            {loadingMessages && (
              <div className="text-sm text-zinc-500 px-2 py-3">Načítám historii…</div>
            )}

            {!loadingMessages && history.length === 0 && !loading && (
              <div className="h-full flex items-center justify-center">
                <div className="text-center max-w-md">
                  <div className="mx-auto h-14 w-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-2xl font-bold mb-4 shadow-lg shadow-indigo-900/40">
                    ✦
                  </div>
                  <h2 className="text-xl font-semibold mb-2">
                    Zdravím, jsem Standa AI
                  </h2>
                  <p className="text-zinc-400 text-sm leading-6 mb-4">
                    Mám přístup k tvým WoT resourcem, finančním transakcím a
                    školním úkolům. Klidně se zeptej na cokoliv z těchto oblastí.
                  </p>
                  <div className="flex flex-col gap-2 text-sm text-left">
                    {[
                      "Co mám dnes dělat?",
                      "Jaký mám plán na tento týden?",
                      "Jak si vedu s plněním cílů?",
                      "Kolik zbývá XP na VZ.55?",
                      "Jaká je moje aktuální finanční bilance?",
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        onClick={() => {
                          setMessage(suggestion);
                        }}
                        className="w-full text-left bg-zinc-800/60 hover:bg-zinc-800 border border-zinc-800 hover:border-zinc-700 rounded-xl px-4 py-3 text-zinc-300 transition-colors"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {history.map((m) => (
              <div
                key={m.id}
                className={`flex gap-3 ${
                  m.role === "user" ? "justify-end" : "justify-start"
                }`}
              >
                {m.role === "assistant" && (
                  <div className="h-9 w-9 shrink-0 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-sm font-bold shadow shadow-indigo-900/40">
                    ✦
                  </div>
                )}
                <div
                  className={`max-w-[85%] md:max-w-[78%] ${
                    m.role === "user"
                      ? "bg-white text-black rounded-br-sm rounded-2xl px-4 py-3.5"
                      : "text-zinc-100"
                  }`}
                >
                  {m.role === "user" ? (
                    <p className="whitespace-pre-wrap leading-7">
                      {m.content}
                    </p>
                  ) : (
                    <div className="space-y-1">
                      {m.content && (
                        <div className="bg-zinc-800/80 border border-zinc-800 rounded-2xl rounded-bl-sm px-4 py-3.5 text-[15px]">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">{formatMarkdown(m.content)}</div>
                            {ttsSupported && ttsEnabled ? (
                              <button
                                type="button"
                                title={activeTtsKey === `text-${m.id}` ? "Zastavit čtení" : "Přečíst nahlas"}
                                onClick={() => {
                                  const key = `text-${m.id}`;
                                  if (activeTtsKey === key) {
                                    stopTts();
                                  } else {
                                    playText(key, m.content, speechLocale);
                                  }
                                }}
                                className={
                                  "shrink-0 h-9 w-9 rounded-xl border transition-colors grid place-items-center text-sm " +
                                  (activeTtsKey === `text-${m.id}`
                                    ? "bg-rose-500/20 border-rose-400/40 text-rose-200 hover:bg-rose-500/30"
                                    : "bg-white/5 border-white/10 text-zinc-200 hover:bg-white/10")
                                }
                              >
                                {activeTtsKey === `text-${m.id}` ? "■" : "🔊"}
                              </button>
                            ) : null}
                          </div>
                        </div>
                      )}
                      {m.plannerCard && (
                        <div className="relative">
                          <PlannerCardRenderer card={m.plannerCard} compact />
                          {ttsSupported && ttsEnabled ? (
                            <button
                              type="button"
                              title={activeTtsKey === `plan-${m.id}` ? "Zastavit čtení plánu" : "Přečíst plán nahlas"}
                              onClick={() => {
                                const key = `plan-${m.id}`;
                                if (activeTtsKey === key) {
                                  stopTts();
                                } else {
                                  const summary = plannerSpeechSummary(
                                    m.plannerCard as unknown as SpeechPlannerCard,
                                  );
                                  playText(key, summary, speechLocale);
                                }
                              }}
                              className={
                                "absolute top-2 right-2 h-9 w-9 rounded-xl border transition-colors grid place-items-center text-sm backdrop-blur " +
                                (activeTtsKey === `plan-${m.id}`
                                  ? "bg-rose-500/25 border-rose-400/40 text-rose-100 hover:bg-rose-500/35"
                                  : "bg-zinc-900/70 border-zinc-700/80 text-zinc-100 hover:bg-zinc-800/80")
                              }
                            >
                              {activeTtsKey === `plan-${m.id}` ? "■" : "🔊"}
                            </button>
                          ) : null}
                        </div>
                      )}
                    </div>
                  )}
                </div>
                {m.role === "user" && (
                  <div className="h-9 w-9 shrink-0 rounded-xl bg-zinc-700 flex items-center justify-center text-sm font-bold">
                    S
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-3 justify-start">
                <div className="h-9 w-9 shrink-0 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-500 flex items-center justify-center text-sm font-bold shadow shadow-indigo-900/40">
                  ✦
                </div>
                <div className="bg-zinc-800/80 border border-zinc-800 rounded-2xl rounded-bl-sm px-4 py-3.5">
                  <ThinkingDots />
                </div>
              </div>
            )}

            {pendingActions.length > 0 && (
              <div className="space-y-3 mt-2">
                {pendingActions.map((action, idx) => {
                  const info = describePendingAction(action);
                  const isConfirming = confirmingIdx === idx;
                  const isFailed = !isConfirming && failedAction?.action === action;
                  const state = isConfirming ? "executing" : isFailed ? "failed" : "pending";
                  return (
                    <div
                      // pokus selhání v klíči → zatřesení se přehraje při každém dalším selhání
                      key={`pa-${idx}-${isFailed ? failedAction?.attempt : 0}`}
                      aria-busy={isConfirming}
                      className={`motion-card relative overflow-hidden mx-2 border bg-gradient-to-br via-zinc-900/80 to-zinc-900/80 rounded-2xl p-4 shadow-lg transition-colors ${
                        state === "failed"
                          ? "motion-shake border-red-500/50 from-red-500/10 shadow-red-950/30"
                          : state === "executing"
                            ? "motion-executing border-sky-500/40 from-sky-500/10 shadow-sky-950/30"
                            : "border-amber-500/30 from-amber-500/10 shadow-amber-950/30"
                      }`}
                    >
                      <div className="flex items-center gap-2 mb-3">
                        <div
                          className={`h-8 w-8 rounded-lg border flex items-center justify-center text-sm font-bold shrink-0 transition-colors ${
                            state === "failed"
                              ? "bg-red-500/20 border-red-500/40 text-red-300"
                              : state === "executing"
                                ? "bg-sky-500/20 border-sky-500/40 text-sky-300"
                                : "bg-amber-500/20 border-amber-500/40 text-amber-300"
                          }`}
                        >
                          {state === "failed" ? "✕" : state === "executing" ? "…" : "!"}
                        </div>
                        <div>
                          <div
                            role="status"
                            className={`text-[11px] uppercase tracking-wider font-semibold ${
                              state === "failed"
                                ? "text-red-300/90"
                                : state === "executing"
                                  ? "text-sky-300/90"
                                  : "text-amber-300/80"
                            }`}
                          >
                            {state === "failed"
                              ? "Provedení selhalo – můžeš zkusit znovu"
                              : state === "executing"
                                ? "Provádím změnu…"
                                : "Standa AI chce provést změnu"}
                          </div>
                          <div className="text-base font-semibold text-white mt-0.5">
                            {info.title}
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-sm mb-3">
                        {info.fields.map((f) => (
                          <div
                            key={f.label}
                            className="flex justify-between items-center gap-3 border-b border-zinc-800/70 pb-1.5 last:border-0"
                          >
                            <span className="text-zinc-400">{f.label}</span>
                            <span className="font-medium text-zinc-100 text-right truncate">
                              {f.value}
                            </span>
                          </div>
                        ))}
                      </div>

                      {info.footer && (
                        <div className="flex justify-between items-center mb-4 bg-zinc-800/60 border border-zinc-800 rounded-xl px-4 py-2.5">
                          <span className="text-zinc-300 text-sm">
                            {info.footer.label}
                          </span>
                          <span className="text-emerald-400 font-semibold text-lg tabular-nums">
                            {info.footer.value}
                          </span>
                        </div>
                      )}

                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => confirmAction(idx)}
                          disabled={isConfirming}
                          className="motion-press flex-1 bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-white font-medium px-4 py-2.5 rounded-xl transition-colors"
                        >
                          {isConfirming ? "Provádím…" : "Potvrdit"}
                        </button>
                        <button
                          type="button"
                          onClick={() => cancelAction(idx)}
                          disabled={isConfirming}
                          className="motion-press flex-1 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 text-zinc-200 font-medium px-4 py-2.5 rounded-xl border border-zinc-700 transition-colors"
                        >
                          Zrušit
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {actionOutcomes.length > 0 && (
              <div className="space-y-2 mt-2" aria-live="polite">
                {actionOutcomes.map((o) => (
                  <div
                    key={o.key}
                    className={`motion-outcome mx-2 rounded-2xl border px-4 py-3 text-sm flex items-center gap-2 ${
                      o.kind === "success"
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                        : "border-zinc-700 bg-zinc-800/60 text-zinc-300"
                    }`}
                  >
                    <span aria-hidden="true">{o.kind === "success" ? "✓" : "↩"}</span>
                    <span className="font-medium">{o.kind === "success" ? "Potvrzeno" : "Zrušeno"}:</span>
                    <span className="truncate">{o.title}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="border-t border-zinc-800 p-3 md:p-5 bg-zinc-900/70 safe-bottom">
            <div
              className={
                "rounded-xl border transition-colors p-2 md:p-2.5 mb-2 text-xs md:text-sm " +
                (speechStatus === "listening"
                  ? "bg-rose-500/10 border-rose-400/30 text-rose-100"
                  : speechStatus === "error"
                    ? "bg-red-500/10 border-red-400/30 text-red-200"
                    : speechStatus === "processing"
                      ? "bg-amber-500/10 border-amber-400/30 text-amber-100"
                      : speechInterim || speechTranscript
                        ? "bg-zinc-800/60 border-zinc-700 text-zinc-200"
                        : "hidden")
              }
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  {speechStatus === "listening" ? (
                    <div className="flex items-center gap-2 font-semibold">
                      <span className="inline-block h-2.5 w-2.5 rounded-full bg-rose-500 animate-pulse" />
                      Poslouchám…
                    </div>
                  ) : speechStatus === "processing" ? (
                    <div className="font-semibold text-amber-200">Zpracovávám řeč…</div>
                  ) : speechError ? (
                    <div className="font-semibold">{speechError}</div>
                  ) : null}
                  {(speechInterim || speechTranscript) && speechStatus === "listening" ? (
                    <div className="mt-1 break-words">
                      {speechTranscript}{" "}
                      <span className="text-zinc-400 italic">{speechInterim || "…"}</span>
                    </div>
                  ) : null}
                </div>
                {(speechStatus === "listening" || speechStatus === "processing" || speechStatus === "error") ? (
                  <button
                    type="button"
                    onClick={() => {
                      stopSpeech();
                    }}
                    className="shrink-0 text-xs px-2.5 py-1 rounded-lg border border-white/10 hover:border-white/20 hover:bg-white/5 transition-colors"
                  >
                    Zastavit
                  </button>
                ) : null}
              </div>
            </div>

            <div className="flex gap-2 items-end">
              <div className="flex-1 min-w-0 flex flex-col gap-2">
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void sendMessage();
                    }
                  }}
                  rows={2}
                  placeholder="Napiš otázku… (Enter = odeslat)"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-xl p-3 md:p-4 outline-none resize-none focus:border-zinc-500 text-sm md:text-base"
                />
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="inline-flex items-center gap-2 text-zinc-400 hover:text-zinc-200 transition-colors select-none cursor-pointer">
                      <input
                        type="checkbox"
                        checked={speechAutoSend}
                        onChange={(e) => setSpeechAutoSend(e.target.checked)}
                        className="accent-indigo-500"
                      />
                      Odeslat automaticky po diktování
                    </label>
                    <label className="inline-flex items-center gap-2 text-zinc-400 hover:text-zinc-200 transition-colors select-none cursor-pointer">
                      <input
                        type="checkbox"
                        checked={ttsEnabled}
                        onChange={(e) => setTtsEnabled(e.target.checked)}
                        disabled={!ttsSupported}
                        className="accent-indigo-500 disabled:opacity-50"
                      />
                      Přečíst odpověď nahlas
                    </label>
                    <div className="flex items-center gap-1.5 text-zinc-400">
                      <span>Jazyk:</span>
                      <select
                        value={speechLocale}
                        onChange={(e) => setSpeechLocale(e.target.value as SpeechLocale)}
                        className="bg-zinc-800 border border-zinc-700 rounded-lg px-2 py-1 text-xs outline-none focus:border-zinc-500"
                      >
                        {SUPPORTED_LOCALES.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="md:hidden text-zinc-500">Enter = odeslat</div>
                </div>
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (speechStatus === "listening" || speechStatus === "processing") {
                        stopSpeech();
                      } else {
                        startSpeech();
                      }
                    }}
                    disabled={!sttSupported || loading}
                    title={
                      sttSupported
                        ? speechStatus === "listening"
                          ? "Zastavit nahrávání"
                          : "Hlasové zadávání (Ctrl+Shift+M)"
                        : "Hlasové zadávání není v tomto prohlížeči podporováno."
                    }
                    className={
                      "grid place-items-center shrink-0 rounded-xl border transition-all select-none " +
                      (speechStatus === "listening"
                        ? "h-[44px] w-[44px] md:h-[50px] md:w-[50px] bg-rose-500/25 border-rose-400/50 text-rose-100 animate-pulse"
                        : speechStatus === "processing"
                          ? "h-[44px] w-[44px] md:h-[50px] md:w-[50px] bg-amber-500/20 border-amber-400/40 text-amber-100"
                          : speechStatus === "error"
                            ? "h-[44px] w-[44px] md:h-[50px] md:w-[50px] bg-red-500/15 border-red-400/40 text-red-200"
                            : "h-[44px] w-[44px] md:h-[50px] md:w-[50px] bg-zinc-800 border-zinc-700 text-zinc-100 hover:bg-zinc-700 hover:border-zinc-600 disabled:opacity-40 disabled:cursor-not-allowed")
                    }
                  >
                    🎤
                  </button>
                  <button
                    type="button"
                    onClick={() => void sendMessage()}
                    disabled={loading || !message.trim() || activeConversationId == null}
                    className="bg-white text-black font-medium px-3 md:px-5 rounded-xl disabled:opacity-40 hover:bg-zinc-200 transition-colors shrink-0 text-sm md:text-base h-[44px] md:h-[50px]"
                  >
                    {loading ? "…" : "Odeslat"}
                  </button>
                </div>
              </div>
            </div>
            {!sttSupported ? (
              <div className="mt-3 text-xs text-zinc-500">
                Hlasové zadávání není v tomto prohlížeči podporováno. Použij novější Chrome nebo Edge pro hlasové ovládání.
              </div>
            ) : (
              <div className="hidden md:flex mt-2 items-center justify-between text-xs text-zinc-500">
                <div>
                  Ctrl+Shift+M = hlasové zadávání · Používají se tvá aktuální data z WoT, Finance a School.
                </div>
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
