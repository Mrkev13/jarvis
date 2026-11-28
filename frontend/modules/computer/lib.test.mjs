// MRK-157: čisté funkce stránky Počítač.
import assert from "node:assert/strict";
import { test } from "node:test";

import { codeMinutesLeft, commandStatus, diskLabel, hasPendingCommand, lastSeenLabel, pctLabel, runningNames, uptimeLabel } from "./lib.ts";

const sp = (x) => x.replace(/\s/g, " ");

test("last seen and uptime labels", () => {
  const now = Date.parse("2026-11-28T10:00:00Z");
  assert.equal(lastSeenLabel(null, now), "zatím se neohlásil");
  assert.equal(lastSeenLabel("2026-11-28T09:59:40Z", now), "právě teď");
  assert.equal(lastSeenLabel("2026-11-28T09:55:00Z", now), "před 5 min");
  assert.equal(lastSeenLabel("2026-11-28T07:00:00Z", now), "před 3 h");
  assert.equal(uptimeLabel(null), "–");
  assert.equal(uptimeLabel(42), "42 min");
  assert.equal(uptimeLabel(125), "2 h 5 min");
  assert.equal(uptimeLabel(60 * 72), "3 dní");
  assert.equal(pctLabel(41.6), "42 %");
});

test("disk, running apps, statuses", () => {
  const d = diskLabel({ name: "C:", free_gb: 120.5, total_gb: 476 });
  assert.equal(sp(d.text), "C: 121 GB volno z 476 GB");
  assert.equal(sp(diskLabel({ name: "D:", free_gb: 12.25, total_gb: 64 }).text), "D: 12,3 GB volno z 64 GB");
  assert.ok(Math.abs(d.freeShare - 120.5 / 476) < 1e-9);
  const device = { apps: [{ id: "wot", name: "World of Tanks" }], status: { running: ["wot", "x"] }, recent: [] };
  assert.deepEqual(runningNames(device), ["World of Tanks", "x"]);
  assert.equal(commandStatus("failed").tone, "danger");
  assert.equal(commandStatus("expired").label, "Propadlo");
  assert.equal(hasPendingCommand([device]), false);
  assert.equal(hasPendingCommand([{ ...device, recent: [{ status: "queued" }] }]), true);
});

test("pairing code countdown", () => {
  const now = Date.parse("2026-11-28T10:00:00Z");
  assert.equal(codeMinutesLeft("2026-11-28T10:09:30Z", now), 10);
  assert.equal(codeMinutesLeft("2026-11-28T09:59:00Z", now), 0);
});
