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
