import test from "node:test";
import assert from "node:assert/strict";
import { greetingText, pickVoice, voiceOptions } from "./hudVoice.ts";
import { parseHudPrefs } from "./hud.ts";

// MRK-136: hlas Jarvise – přirozené hlasy před robotickými, britská angličtina, uložený výběr.
const V = [
  { name: "Microsoft Jakub - Czech (Czech)", lang: "cs-CZ", voiceURI: "jakub", localService: true },
  { name: "Google čeština", lang: "cs-CZ", voiceURI: "g-cs", localService: false },
  { name: "Microsoft Antonin Online (Natural) - Czech", lang: "cs-CZ", voiceURI: "antonin", localService: false },
  { name: "Google US English", lang: "en-US", voiceURI: "g-us", localService: false },
  { name: "Google UK English Female", lang: "en-GB", voiceURI: "g-uk-f", localService: false },
  { name: "Google UK English Male", lang: "en-GB", voiceURI: "g-uk-m", localService: false },
  { name: "Microsoft Hedda", lang: "de-DE", voiceURI: "hedda", localService: true },
];

test("best voice: natural / Google before robotic, British male for English", () => {
  assert.equal(pickVoice(V, { voiceLang: "cs", voiceURI: null }).voiceURI, "antonin");
  assert.equal(pickVoice(V, { voiceLang: "en", voiceURI: null }).voiceURI, "g-uk-m");
  assert.deepEqual(voiceOptions(V, "cs").map((v) => v.voiceURI), ["antonin", "g-cs", "jakub"]);
  assert.ok(!voiceOptions(V, "en").some((v) => v.lang.startsWith("de")));
});

test("saved voice wins while it exists and fits the language", () => {
  assert.equal(pickVoice(V, { voiceLang: "cs", voiceURI: "jakub" }).voiceURI, "jakub");
  assert.equal(pickVoice(V, { voiceLang: "cs", voiceURI: "gone" }).voiceURI, "antonin");
  assert.equal(pickVoice(V, { voiceLang: "cs", voiceURI: "g-uk-m" }).voiceURI, "antonin", "anglický hlas na český text ne");
  assert.equal(pickVoice([], { voiceLang: "en", voiceURI: null }), null);
});

test("greeting text by language and Prague hour", () => {
  assert.equal(greetingText("en", 14), "Good afternoon, Standa. All systems online.");
  assert.equal(greetingText("en", 8), "Good morning, Standa. All systems online.");
  assert.equal(greetingText("en", 2), "Burning the midnight oil, Standa? All systems online.");
  assert.equal(greetingText("cs", 14), "Dobré odpoledne, Stando. Všechny systémy jsou online.");
  assert.equal(greetingText("cs", 2), "Pořád vzhůru, Stando? Všechny systémy jsou online.");
});

test("prefs keep voice language and choice, reject junk", () => {
  assert.deepEqual(parseHudPrefs('{"voice":true,"voiceLang":"en","voiceURI":"g-uk-m"}'),
    { sounds: false, voice: true, voiceLang: "en", voiceURI: "g-uk-m" });
  assert.deepEqual(parseHudPrefs('{"voiceLang":"de","voiceURI":5}'), { sounds: false, voice: false, voiceLang: "cs", voiceURI: null });
});

test("studio voice clips follow the greeting day parts", async () => {
  const { greetingClip, usesStudioVoice } = await import("./hudVoice.ts");
  const { existsSync } = await import("node:fs");
  assert.equal(greetingClip("en", 14), "/jarvis/voice/en-afternoon.mp3");
  assert.equal(greetingClip("en", 9), "/jarvis/voice/en-morning.mp3");
  assert.equal(greetingClip("cs", 11), "/jarvis/voice/cs-day.mp3", "česky „Dobré odpoledne“ už od 10 h");
  assert.equal(greetingClip("cs", 2), "/jarvis/voice/cs-night.mp3");
  for (const lang of ["cs", "en"]) for (let h = 0; h < 24; h++) {
    const file = new URL(`../public${greetingClip(lang, h)}`, import.meta.url);
    assert.ok(existsSync(file), `chybí klip ${greetingClip(lang, h)}`);
  }
  assert.equal(usesStudioVoice({ voiceURI: null }), true);
  assert.equal(usesStudioVoice({ voiceURI: "piper" }), true);
  assert.equal(usesStudioVoice({ voiceURI: "g-uk-m" }), false);
});

// Codex review #106: přihlášení nesmí useknout pozdrav – čeká na konec, pojistka pokryje nejdelší klip i načtení.
test("login waits for the whole greeting; the safety cap covers the longest clip", async () => {
  const { greetThenGo, LOGIN_GREETING_MAX_MS } = await import("./hudVoice.ts");
  const { readdirSync, statSync } = await import("node:fs");
  const dir = new URL("../public/jarvis/voice/", import.meta.url);
  // MP3 64 kb/s CBR → délka ≈ bajty * 8 / 64000
  const longestMs = Math.max(...readdirSync(dir).filter((f) => f.endsWith(".mp3"))
    .map((f) => (statSync(new URL(f, dir)).size * 8) / 64000 * 1000));
  assert.ok(longestMs > 5000, "české klipy jsou delší než původních 4,5 s");
  assert.ok(LOGIN_GREETING_MAX_MS >= longestMs + 2500, `pojistka ${LOGIN_GREETING_MAX_MS} ms vs. klip ${Math.round(longestMs)} ms`);

  // simulované hodiny: pozdrav trvá 5,6 s – přesměrování až po něm, ne v 4,5 s
  const events = [];
  let clock = 0;
  const timers = [];
  const wait = (ms) => new Promise((r) => timers.push({ at: clock + ms, r }));
  const say = () => new Promise((r) => timers.push({ at: clock + 5600, r: () => { events.push(`dořečeno@${clock}`); r(); } }));
  const run = greetThenGo(say, () => events.push(`odchod@${clock}`), LOGIN_GREETING_MAX_MS, wait);
  for (const t of [...timers].sort((a, b) => a.at - b.at)) { clock = t.at; t.r(); await new Promise((r) => setImmediate(r)); }
  assert.equal(await run, true);
  assert.deepEqual(events.slice(0, 2), ["dořečeno@5600", "odchod@5600"]);

  // zaseknuté přehrávání: pojistka odejde a vrátí false (pozdrav se neoznačí jako odehraný)
  const stuck = await greetThenGo(() => new Promise(() => {}), () => {}, 10, (ms) => new Promise((r) => setTimeout(r, ms)));
  assert.equal(stuck, false);
});
