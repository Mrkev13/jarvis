import test from "node:test";
import assert from "node:assert/strict";
import { bootGreeting, pragueHour, shouldBoot } from "./boot.ts";

// MRK-131: start systému – pozdrav podle pražského času, jen jednou za relaci, nikdy při omezeném pohybu.
test("greeting follows the Prague clock", () => {
  assert.equal(bootGreeting(7), "Dobré ráno, Stando");
  assert.equal(bootGreeting(14), "Dobré odpoledne, Stando");
  assert.equal(bootGreeting(20), "Dobrý večer, Stando");
  assert.equal(bootGreeting(2), "Pořád vzhůru, Stando?");
  // 23. 11. 2026 06:30 UTC = 07:30 v Praze (zimní čas), 23:30 UTC = 00:30 další den
  assert.equal(pragueHour(new Date("2026-11-23T06:30:00Z")), 7);
  assert.equal(pragueHour(new Date("2026-11-23T23:30:00Z")), 0);
  assert.equal(pragueHour(new Date("2026-07-01T06:30:00Z")), 8, "letní čas");
});

test("boot shows once per session and never with reduced motion", () => {
  const base = { seen: false, reducedMotion: false, automated: false, force: false };
  assert.equal(shouldBoot(base), true);
  assert.equal(shouldBoot({ ...base, seen: true }), false);
  assert.equal(shouldBoot({ ...base, automated: true }), false);
  assert.equal(shouldBoot({ ...base, automated: true, seen: true, force: true }), true);
  assert.equal(shouldBoot({ ...base, reducedMotion: true, force: true }), false);
});
