export type SpeechLocale = "cs-CZ" | "en-US";

export type RecorderStatus = "idle" | "listening" | "processing" | "error";

export const STORAGE_KEYS = {
  voiceLang: "sh:voice:lang",
  autoSend: "sh:voice:auto-send",
  ttsEnabled: "sh:voice:tts-enabled",
} as const;

export const DEFAULT_LOCALE: SpeechLocale = "cs-CZ";
export const SUPPORTED_LOCALES: Array<{ value: SpeechLocale; label: string }> = [
  { value: "cs-CZ", label: "Čeština" },
  { value: "en-US", label: "English" },
];

export function getStoredLocale(defaultFallback: SpeechLocale = DEFAULT_LOCALE): SpeechLocale {
  if (typeof window === "undefined") return defaultFallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.voiceLang);
    if (raw === "cs-CZ" || raw === "en-US") return raw;
  } catch {
    /* ignore */
  }
  return defaultFallback;
}

export function setStoredLocale(locale: SpeechLocale) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEYS.voiceLang, locale);
  } catch {
    /* ignore */
  }
}

export function getStoredAutoSend(defaultFallback = false): boolean {
  if (typeof window === "undefined") return defaultFallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.autoSend);
    if (raw === "1" || raw === "true") return true;
    if (raw === "0" || raw === "false") return false;
  } catch {
    /* ignore */
  }
  return defaultFallback;
}

export function setStoredAutoSend(value: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEYS.autoSend, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function getStoredTtsEnabled(defaultFallback = true): boolean {
  if (typeof window === "undefined") return defaultFallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEYS.ttsEnabled);
    if (raw === "1" || raw === "true") return true;
    if (raw === "0" || raw === "false") return false;
  } catch {
    /* ignore */
  }
  return defaultFallback;
}

export function setStoredTtsEnabled(value: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEYS.ttsEnabled, value ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function isSpeechRecognitionSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as {
    SpeechRecognition?: unknown;
    webkitSpeechRecognition?: unknown;
  };
  return Boolean(w.SpeechRecognition || w.webkitSpeechRecognition);
}

export function isSpeechSynthesisSupported(): boolean {
  if (typeof window === "undefined") return false;
  return typeof window.speechSynthesis !== "undefined";
}

export function detectSpeechLocaleFromText(text: string | null | undefined): SpeechLocale {
  const t = String(text || "").toLowerCase();
  const csLetters = /[áčďéěíňóřšťúůýž]/;
  const csWords = /\b(dnes|týden|týdenní|plán|cíl|cíle|bilance|úkol|škola|práce|kolik|jak|co|mám|dělat|dělat|budu|udělat|co|za|tento|měsíc)\b/;
  if (csLetters.test(t) || csWords.test(t)) return "cs-CZ";
  const enWords = /\b(today|week|plan|goal|goals|balance|work|how|what|my|do|have|should|month|assignment|exam|xp|finance|school)\b/;
  if (enWords.test(t)) return "en-US";
  const latinScore = (t.match(/[a-z]/gi) || []).length;
  if (latinScore === 0) return DEFAULT_LOCALE;
  return DEFAULT_LOCALE;
}

export function cleanTextForSpeech(content: string | null | undefined): string {
  if (content == null) return "";
  let text = String(content);

  text = text.replace(/```[\s\S]*?```/g, " ");
  text = text.replace(/`{1,2}[^`]*`{1,2}/g, " ");

  text = text.replace(/^\s{0,3}#{1,6}\s*([^\n]*)$/gm, "$1.");
  text = text.replace(/^\s*[-*+]\s+/gm, " ");
  text = text.replace(/^\s*\d+\.\s+/gm, " ");
  text = text.replace(/^>+\s*/gm, " ");

  text = text.replace(/\*\*([^*]+)\*\*/g, "$1");
  text = text.replace(/__([^_]+)__/g, "$1");
  text = text.replace(/\*([^*\n]+)\*/g, "$1");
  text = text.replace(/_([^_\n]+)_/g, "$1");

  text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, " ");
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|[^)\s]+\.[^)\s]+)\)/g, "$1");
  text = text.replace(/https?:\/\/[^\s]+/g, " ");
  text = text.replace(/\bwww\.\S+/gi, " ");

  text = text.replace(/<[^>]+>/g, " ");

  text = text.replace(/[<>{}|=]+/g, " ");
  text = text.replace(/\u00a0/g, " ");

  text = text.replace(/\n{3,}/g, "\n\n");
  text = text.replace(/[ \t]{2,}/g, " ");
  text = text.replace(/\s*([.!?])\s*/g, "$1 ");
  text = text.replace(/\s*,\s*/g, ", ");
  text = text.replace(/\s{2,}/g, " ").trim();

  if (text.length > 4000) {
    const cut = text.slice(0, 4000);
    const lastStop = Math.max(
      cut.lastIndexOf(". "),
      cut.lastIndexOf("? "),
      cut.lastIndexOf("! "),
    );
    return (lastStop > 3500 ? cut.slice(0, lastStop + 1) : cut).trim();
  }
  return text;
}

type PlannerDailyWeekly = {
  card_type: "daily" | "weekly";
  payload: {
    summary?: string | null;
    actions?: Array<{ title?: string | null; reason?: string | null; priority?: number | null; area?: string | null }> | null;
  };
};

type PlannerGoalReview = {
  card_type: "goal_review";
  payload: {
    summary?: string | null;
    goals?: Array<{ title?: string | null; progress?: number | null; area?: string | null; priority?: string | null }> | null;
  };
};

export type SpeechPlannerCard = PlannerDailyWeekly | PlannerGoalReview;

export function plannerSpeechSummary(card: SpeechPlannerCard | null | undefined): string {
  if (!card) return "";
  const type = card.card_type;
  const payload = card.payload as unknown as Record<string, unknown> | undefined;
  const summary = cleanTextForSpeech((payload?.summary as string | undefined) || "");

  if (type === "daily") {
    const parts: string[] = [];
    parts.push(summary || "Dnešní plán.");
    const actions = (payload?.actions as Array<Record<string, unknown>> | undefined) || [];
    const top = actions.slice(0, 3);
    const cs = ["První", "Druhé", "Třetí"];
    top.forEach((a, idx) => {
      const title = cleanTextForSpeech(String(a.title ?? ""));
      if (!title) return;
      parts.push(`${cs[idx] ?? (idx + 1) + ". položka"}: ${title}.`);
    });
    return parts.join(" ");
  }

  if (type === "weekly") {
    const parts: string[] = [];
    parts.push(summary || "Týdenní plán.");
    const actions = (payload?.actions as Array<Record<string, unknown>> | undefined) || [];
    const top = actions.slice(0, 3);
    const cs = ["První priorita", "Druhá priorita", "Třetí priorita"];
    top.forEach((a, idx) => {
      const title = cleanTextForSpeech(String(a.title ?? ""));
      if (!title) return;
      parts.push(`${cs[idx] ?? (idx + 1) + ". priorita"}: ${title}.`);
    });
    return parts.join(" ");
  }

  if (type === "goal_review") {
    const parts: string[] = [];
    parts.push(summary || "Přehled cílů.");
    const goals = (payload?.goals as Array<Record<string, unknown>> | undefined) || [];
    const top = goals.slice(0, 4);
    top.forEach((g) => {
      const title = cleanTextForSpeech(String(g.title ?? ""));
      const progress = Number(g.progress ?? 0);
      if (!title) return;
      parts.push(`${title}: ${progress} procent.`);
    });
    return parts.join(" ");
  }

  return summary;
}

export function chooseVoice(locale: SpeechLocale, voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  if (!voices.length) return null;
  const exact = voices.find(
    (v) => (v.lang || "").toLowerCase() === locale.toLowerCase(),
  );
  if (exact) return exact;
  const prefix = locale.split("-")[0].toLowerCase();
  const prefixMatch = voices.find((v) =>
    (v.lang || "").toLowerCase().startsWith(prefix),
  );
  if (prefixMatch) return prefixMatch;
  const fallback = voices.find((v) => /^(cs|en)/i.test(v.lang || ""));
  return fallback || voices[0] || null;
}

export type TtsHandle = { stop: () => void; isSpeaking: () => boolean };

export function speakText(text: string, locale: SpeechLocale): TtsHandle {
  const empty: TtsHandle = { stop: () => {}, isSpeaking: () => false };
  if (!text || !isSpeechSynthesisSupported()) return empty;

  const synth = window.speechSynthesis;
  const clean = cleanTextForSpeech(text);
  if (!clean) return empty;

  try {
    synth.cancel();
  } catch {
    /* ignore */
  }

  const utter = new SpeechSynthesisUtterance(clean);
  utter.lang = locale;
  utter.rate = 1.0;
  utter.pitch = 1.0;
  utter.volume = 1.0;

  const voices = synth.getVoices?.() || [];
  const v = chooseVoice(locale, voices);
  if (v) {
    utter.voice = v;
  }

  let speaking = true;
  const done = () => {
    speaking = false;
  };
  utter.onend = done;
  utter.onerror = done;

  synth.speak(utter);

  return {
    stop: () => {
      try {
        synth.cancel();
      } catch {
        /* ignore */
      }
      speaking = false;
    },
    isSpeaking: () => speaking && typeof synth.speaking === "boolean" ? synth.speaking : speaking,
  };
}
