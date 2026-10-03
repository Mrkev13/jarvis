// Roadmap 4A: sdílené formátování (cs-CZ, Europe/Prague pro okamžiky).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatCzk,
  formatDate,
  formatDateTime,
  formatDays,
  formatHours,
  formatNumber,
  formatPercent,
  formatRelativeDays,
  formatSigned,
  parseApiInstant,
  plural,
} from "./format.ts";

// Intl cs-CZ odděluje tisíce nezlomitelnou mezerou (U+00A0).
const n = (s) => s.replace(/ /g, " ");

test("formatNumber uses Czech separators and handles missing values", () => {
  assert.equal(n(formatNumber(12345.678)), "12 345,68");
  assert.equal(n(formatNumber(1500, 0)), "1 500");
  assert.equal(formatNumber(null), "–");
  assert.equal(formatNumber(undefined), "–");
  assert.equal(formatNumber(Number.NaN), "–");
});

test("money, hours, percent", () => {
  assert.equal(n(formatCzk(4821.4)), "4 821 Kč");
  assert.equal(n(formatCzk(12.5)), "12,5 Kč");
  assert.equal(formatHours(12.25), "12,3 h");
  assert.equal(formatPercent(41.6), "42 %");
  assert.equal(formatPercent(140, true), "100 %");
});

test("signed values use a real minus", () => {
  assert.equal(formatSigned(12, "12 %"), "+12 %");
  assert.equal(formatSigned(-4, "-4 h"), "−4 h");
  assert.equal(formatSigned(0, "0"), "0");
});

test("Czech plurals and relative days", () => {
  assert.equal(plural(1, "den", "dny", "dní"), "den");
  assert.equal(plural(3, "den", "dny", "dní"), "dny");
  assert.equal(plural(5, "den", "dny", "dní"), "dní");
  assert.equal(formatDays(0), "0 dní");
  assert.equal(formatRelativeDays(0), "dnes");
  assert.equal(formatRelativeDays(1), "zítra");
  assert.equal(formatRelativeDays(4), "za 4 dny");
  assert.equal(formatRelativeDays(-2), "před 2 dny");
});

test("date-only values are not shifted by time zones", () => {
  assert.equal(formatDate("2026-10-05"), "5. 10. 2026");
  assert.equal(formatDate("2026-10-05", false), "5. 10.");
  assert.equal(formatDate(null), "–");
});

test("instants are shown in Prague time (summer and winter)", () => {
  assert.equal(formatDateTime("2026-10-05T06:05:00Z"), "5. 10. 8:05");
  assert.equal(formatDateTime("2026-12-05T23:30:00Z"), "6. 12. 0:30");
  assert.equal(formatDate("2026-12-31T23:30:00Z"), "1. 1. 2027");
});

test("naive API timestamps are UTC, not browser-local time", () => {
  // backend: naive UTC isoformat() bez zóny → 17:00 UTC = 19:00 v Praze (SELČ)
  assert.equal(formatDateTime("2026-10-11T17:00:00"), "11. 10. 19:00");
  assert.equal(formatDateTime("2026-10-11 17:00:00.123456"), "11. 10. 19:00");
  assert.equal(formatDateTime("2026-10-11T17:00:00+02:00"), "11. 10. 17:00");
  assert.equal(parseApiInstant("2026-12-01T10:00:00").toISOString(), "2026-12-01T10:00:00.000Z");
});
