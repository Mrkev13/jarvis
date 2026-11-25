/**
 * MRK-133: Jarvis HUD – předvolby jen v tomto prohlížeči (zvuky, hlasový pozdrav), denní doba a „Mise splněna".
 * Čisté funkce kvůli testům (hud.test.mjs); úložiště je jen pohodlí (soukromé okno = výchozí hodnoty).
 */
import type { DomainEvent } from "./domainEvents.ts";

/** MRK-136: `voiceLang` = jazyk pozdravu (cs / britská en), `voiceURI` = vybraný hlas prohlížeče (null = nejlepší dostupný). */
export type HudPrefs = { sounds: boolean; voice: boolean; voiceLang: "cs" | "en"; voiceURI: string | null };
export const HUD_PREFS_KEY = "sh:hud:prefs";
export const HUD_PREFS_EVENT = "sh:hud:prefs";
export const DEFAULT_HUD_PREFS: HudPrefs = { sounds: false, voice: false, voiceLang: "cs", voiceURI: null };

export function parseHudPrefs(raw: string | null): HudPrefs {
  try {
    const v = raw ? JSON.parse(raw) : null;
    if (v && typeof v === "object") {
      return {
        sounds: v.sounds === true,
        voice: v.voice === true,
        voiceLang: v.voiceLang === "en" ? "en" : "cs",
        voiceURI: typeof v.voiceURI === "string" && v.voiceURI.length > 0 && v.voiceURI.length < 300 ? v.voiceURI : null,
      };
    }
  } catch {
    /* poškozená hodnota = výchozí */
  }
  return { ...DEFAULT_HUD_PREFS };
}

export function readHudPrefs(): HudPrefs {
  if (typeof window === "undefined") return { ...DEFAULT_HUD_PREFS };
  try {
    return parseHudPrefs(window.localStorage.getItem(HUD_PREFS_KEY));
  } catch {
    return { ...DEFAULT_HUD_PREFS };
  }
}

export function writeHudPrefs(prefs: HudPrefs): void {
  try {
    window.localStorage.setItem(HUD_PREFS_KEY, JSON.stringify(prefs));
  } catch {
    /* jen se neuloží */
  }
  window.dispatchEvent(new CustomEvent(HUD_PREFS_EVENT, { detail: prefs }));
}

/** Denní doba pro barvu HUD (pražská hodina 0–23). */
export type Daypart = "morning" | "day" | "evening" | "night";
export function daypartFor(hour: number): Daypart {
  if (hour >= 5 && hour < 10) return "morning";
  if (hour >= 10 && hour < 18) return "day";
  if (hour >= 18 && hour < 23) return "evening";
  return "night";
}

/** „Mise splněna" – čerstvé doménové události, které stojí za oslavu. Text bez osobních dat (jen typ a číslo). */
export type Mission = { title: string; detail: string };
const MISSIONS: Record<string, (e: DomainEvent) => Mission | null> = {
  "school.assignment.completed": () => ({ title: "Mise splněna", detail: "Úkol hotový" }),
  // MRK-135: splnění cíle (backend goals.goal.completed) – bez názvu cíle, jen fakt
  "goals.goal.completed": () => ({ title: "Mise splněna", detail: "Cíl splněný" }),
  "school.exam.closed": (e) => (e.payload.outcome === "failed" ? null : { title: "Mise splněna", detail: "Zkouška uzavřená" }),
  "wow.character.level_up": (e) => {
    const level = typeof e.payload.level === "number" ? e.payload.level : null;
    const target = typeof e.payload.target_level === "number" ? e.payload.target_level : null;
    if (level === null) return null;
    return { title: target !== null && level >= target ? "Cíl dosažen" : "Level up", detail: `Postava je na levelu ${level}` };
  },
  // MRK-106: první M tanku zjištěné z Wargaming API
  "wot.mastery.ace_detected": () => ({ title: "Mise splněna", detail: "Nové M ve WoT" }),
  // MRK-128: položka ze seznamu „chci získat" se objevila ve sbírce
  "wow.collection.acquired": (e) => ({
    title: "Mise splněna",
    detail: e.payload.kind === "achievement" ? "Achievement získaný" : e.payload.kind === "pet" ? "Nový mazlíček ve sbírce" : "Nový mount ve sbírce",
  }),
};
export const MISSION_FRESH_MS = 2 * 60 * 1000;

export function missionFor(e: DomainEvent, now: number = Date.now()): Mission | null {
  const map = MISSIONS[e.type];
  if (!map) return null;
  const at = Date.parse(e.occurred_at);
  if (!Number.isFinite(at) || now - at > MISSION_FRESH_MS) return null;
  return map(e);
}

/** Text hlasového pozdravu (krátký, bez jména systému – Jarvis mluví za sebe). */
export function voiceGreeting(greeting: string): string {
  return `${greeting.replace(/[?]$/, "?")}${/[?!.]$/.test(greeting) ? "" : "."} Všechny systémy jsou online.`;
}

/** Okno-událost: znovu přehrát start systému (Nastavení → Jarvis HUD → BootSequence). */
export const BOOT_REPLAY_EVENT = "sh:hud:boot";

/** Okno-událost pro „Mise splněna" (DomainEventsBridge → MissionComplete). */
export const MISSION_EVENT = "sh:hud:mission";
export function announceMission(m: Mission): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent<Mission>(MISSION_EVENT, { detail: m }));
}
