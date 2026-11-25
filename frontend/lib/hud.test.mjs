import test from "node:test";
import assert from "node:assert/strict";
import { daypartFor, missionFor, parseHudPrefs, voiceGreeting } from "./hud.ts";

// MRK-133: Jarvis HUD vlna 3 – předvolby, denní doba, „Mise splněna", hlasový pozdrav.
test("prefs default to off and survive garbage", () => {
  assert.deepEqual(parseHudPrefs(null), { sounds: false, voice: false, voiceLang: "cs", voiceURI: null });
  assert.deepEqual(parseHudPrefs("{nope"), { sounds: false, voice: false, voiceLang: "cs", voiceURI: null });
  assert.deepEqual(parseHudPrefs('{"sounds":true,"voice":"yes"}'), { sounds: true, voice: false, voiceLang: "cs", voiceURI: null });
});

test("daypart by Prague hour", () => {
  assert.deepEqual([4, 5, 9, 10, 17, 18, 22, 23].map(daypartFor), ["night", "morning", "morning", "day", "day", "evening", "evening", "night"]);
});

const NOW = Date.parse("2026-11-23T18:00:00Z");
const ev = (type, payload = {}, ago = 10_000) => ({ id: 1, type, module_id: null, aggregate_type: "x", aggregate_id: "1",
  occurred_at: new Date(NOW - ago).toISOString(), payload });

test("mission only for fresh completions", () => {
  assert.deepEqual(missionFor(ev("school.assignment.completed"), NOW), { title: "Mise splněna", detail: "Úkol hotový" });
  assert.equal(missionFor(ev("school.exam.closed", { outcome: "failed" }), NOW), null);
  assert.equal(missionFor(ev("school.exam.closed", { outcome: "passed" }), NOW).detail, "Zkouška uzavřená");
  assert.deepEqual(missionFor(ev("wow.character.level_up", { level: 60, target_level: 60 }), NOW), { title: "Cíl dosažen", detail: "Postava je na levelu 60" });
  assert.equal(missionFor(ev("wow.character.level_up", { level: 24, target_level: 60 }), NOW).title, "Level up");
  assert.deepEqual(missionFor(ev("wot.mastery.ace_detected", { milestone_id: 1, tank_id: 2, tier: 8 }), NOW), { title: "Mise splněna", detail: "Nové M ve WoT" });
  // MRK-128: položka ze seznamu „chci získat" je ve sbírce
  assert.deepEqual(missionFor(ev("wow.collection.acquired", { wish_id: 1, kind: "mount" }), NOW), { title: "Mise splněna", detail: "Nový mount ve sbírce" });
  assert.equal(missionFor(ev("wow.collection.acquired", { wish_id: 2, kind: "achievement" }), NOW).detail, "Achievement získaný");
  assert.equal(missionFor(ev("school.assignment.completed", {}, 5 * 60_000), NOW), null, "replay starých událostí neslaví");
  assert.equal(missionFor(ev("habits.entry.done"), NOW), null);
  assert.deepEqual(missionFor(ev("goals.goal.completed", { goal_id: 3, previous_progress: 80 }), NOW), { title: "Mise splněna", detail: "Cíl splněný" });
  assert.equal(missionFor(ev("finance.import.completed"), NOW), null, "finance nikdy");
});

test("voice greeting sentence", () => {
  assert.equal(voiceGreeting("Dobrý večer, Stando"), "Dobrý večer, Stando. Všechny systémy jsou online.");
  assert.equal(voiceGreeting("Pořád vzhůru, Stando?"), "Pořád vzhůru, Stando? Všechny systémy jsou online.");
});
