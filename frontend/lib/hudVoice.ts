/**
 * MRK-136: hlas Jarvise – výběr hlasu prohlížeče, text pozdravu (česky / britsky anglicky) a klidnější přednes.
 * Čisté funkce (hudVoice.test.mjs) + tenká vrstva nad speechSynthesis. Prohlížeč smí mluvit jen po interakci.
 */
import { bootGreeting } from "./boot.ts";
import type { HudPrefs } from "./hud.ts";

/** sessionStorage: pozdrav už v této relaci zazněl (po PINu na přihlášení). */
export const VOICE_SPOKEN_KEY = "standa-hub-voice-spoken";

export type VoiceLike = { name: string; lang: string; voiceURI: string; localService?: boolean };

/** Přirozené / online hlasy znějí výrazně lépe než staré robotické (Microsoft Jakub, eSpeak…). */
export function voiceScore(v: VoiceLike, lang: "cs" | "en"): number {
  const l = (v.lang || "").toLowerCase().replace("_", "-");
  const name = v.name || "";
  let s = 0;
  if (lang === "cs") {
    if (!l.startsWith("cs")) return -1;
  } else {
    if (!l.startsWith("en")) return -1;
    if (l === "en-gb") s += 4; // Jarvis je Brit
    if (/\b(male|ryan|george|daniel|arthur|oliver|thomas)\b/i.test(name)) s += 3;
    if (/\b(female|libby|sonia|hazel|susan|kate|serena|martha)\b/i.test(name)) s -= 1;
  }
  if (/natural|neural|online/i.test(name)) s += 5;
  if (/google/i.test(name)) s += 3;
  if (v.localService === false) s += 1;
  if (/espeak/i.test(name)) s -= 3;
  return s;
}

/** Hlasy pro výběr v Nastavení: jen čeština a angličtina, nejlepší nahoře. */
export function voiceOptions(voices: VoiceLike[], lang: "cs" | "en"): VoiceLike[] {
  return voices
    .map((v) => ({ v, s: voiceScore(v, lang) }))
    .filter((x) => x.s >= 0)
    .sort((a, b) => b.s - a.s || a.v.name.localeCompare(b.v.name))
    .map((x) => x.v);
}

/** Vybraný hlas (pokud ho prohlížeč pořád má a sedí k jazyku), jinak nejlepší dostupný. */
export function pickVoice<T extends VoiceLike>(voices: T[], prefs: Pick<HudPrefs, "voiceLang" | "voiceURI">): T | null {
  const chosen = prefs.voiceURI ? voices.find((v) => v.voiceURI === prefs.voiceURI && voiceScore(v, prefs.voiceLang) >= 0) : undefined;
  if (chosen) return chosen;
  return (voiceOptions(voices, prefs.voiceLang)[0] as T | undefined) ?? null;
}

/** Text pozdravu podle jazyka a pražské hodiny. */
export function greetingText(lang: "cs" | "en", hour: number): string {
  if (lang === "en") {
    const part = hour >= 5 && hour < 12 ? "Good morning" : hour >= 12 && hour < 18 ? "Good afternoon" : hour >= 18 && hour < 23 ? "Good evening" : null;
    return part ? `${part}, Standa. All systems online.` : "Burning the midnight oil, Standa? All systems online.";
  }
  const g = bootGreeting(hour);
  return `${g}${/[?!.]$/.test(g) ? "" : "."} Všechny systémy jsou online.`;
}

/** Chrome načítá seznam hlasů asynchronně – první volání getVoices() bývá prázdné. Počká nejvýš `ms`. */
export function voicesReady(ms = 600): Promise<void> {
  return new Promise((resolve) => {
    const synth = typeof window !== "undefined" ? window.speechSynthesis : undefined;
    if (!synth || (synth.getVoices?.() ?? []).length) return resolve();
    const done = () => {
      synth.removeEventListener?.("voiceschanged", done);
      resolve();
    };
    synth.addEventListener?.("voiceschanged", done);
    window.setTimeout(done, ms);
  });
}

/** Klidný přednes: o něco pomalejší a hlubší než výchozí. Vrací promise, která skončí po dořečení (nebo chybě). */
export async function speakAsJarvis(text: string, prefs: Pick<HudPrefs, "voiceLang" | "voiceURI">): Promise<void> {
  if (typeof window === "undefined" || !window.speechSynthesis || !text) return;
  await voicesReady();
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    const utter = new SpeechSynthesisUtterance(text);
    const voice = pickVoice(synth.getVoices?.() ?? [], prefs);
    utter.lang = voice?.lang || (prefs.voiceLang === "en" ? "en-GB" : "cs-CZ");
    if (voice) utter.voice = voice;
    utter.rate = 0.94;
    utter.pitch = 0.88;
    utter.onend = () => resolve();
    utter.onerror = () => resolve();
    try {
      synth.cancel();
      synth.speak(utter);
    } catch {
      resolve();
    }
  });
}
