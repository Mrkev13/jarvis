// MRK-41: ruční rozvrh – výchozí semestr, kontrola formuláře, seskupení po dnech, popisky výjimek.
import assert from "node:assert/strict";
import { test } from "node:test";

import { byWeekday, defaultSemester, draftFrom, draftPayload, mondayOf, emptyDraft, exceptionLabel, nextWeekday, validateDraft } from "./timetableLib.ts";

test("default validity follows the current semester", () => {
  assert.deepEqual(defaultSemester("2026-11-26"), { valid_from: "2026-10-01", valid_until: "2027-01-31" });
  assert.deepEqual(defaultSemester("2027-01-10"), { valid_from: "2026-10-01", valid_until: "2027-01-31" });
  assert.deepEqual(defaultSemester("2027-03-01"), { valid_from: "2027-02-15", valid_until: "2027-05-31" });
  assert.deepEqual(defaultSemester("2027-07-01"), { valid_from: "2027-07-01", valid_until: "2027-11-01" });
});

test("form validation and payload", () => {
  const d = emptyDraft("2026-11-26", "3");
  assert.equal(validateDraft(d), null);
  assert.equal(validateDraft({ ...d, subject_id: "" }), "Vyber předmět.");
  assert.equal(validateDraft({ ...d, end: "08:00" }), "Konec musí být po začátku.");
  assert.equal(validateDraft({ ...d, start: "9:00" }), "Čas ve tvaru HH:MM.");
  assert.equal(validateDraft({ ...d, valid_until: "2026-09-01" }), "„Platí do“ musí být po „Platí od“.");
  assert.deepEqual(draftPayload({ ...d, room: "  S5 ", weekday: "2" }, "2026-11-26"), {
    subject_id: 3, kind: "lecture", weekday: 2, start: "09:00", end: "10:30", room: "S5", valid_from: "2026-10-01", valid_until: "2027-01-31",
    every: 1, week_anchor: null,
  });
  assert.equal(draftPayload({ ...d, room: " " }, "2026-11-26").room, null);
});

test("grouping by weekday and labels", () => {
  const e = (id, weekday, start) => ({ id, weekday, start, end: "", exceptions: [] });
  const g = byWeekday([e(1, 2, "12:00"), e(2, 0, "10:00"), e(3, 0, "08:00")]);
  assert.deepEqual(g.map((d) => [d.label, d.entries.map((x) => x.id)]), [["Pondělí", [3, 2]], ["Středa", [1]]]);
  assert.equal(exceptionLabel({ date: "2026-10-12", action: "cancel", starts_at: null, ends_at: null }), "zrušeno 12. 10.");
  assert.equal(exceptionLabel({ date: "2026-10-19", action: "move", starts_at: "2026-10-21T13:00:00+02:00", ends_at: null }), "19. 10. → 21. 10. 13:00");
  assert.equal(nextWeekday("2026-11-26", 0), "2026-11-30", "čtvrtek → pondělí");
  assert.equal(nextWeekday("2026-11-30", 0), "2026-11-30", "pondělí zůstane");
});

test("MRK-142: rhythm every other week round-trips through the form", () => {
  const d = emptyDraft("2026-11-26", "3");
  assert.equal(d.rhythm, "weekly");
  assert.equal(mondayOf("2026-11-26"), "2026-11-23");
  assert.equal(mondayOf("2026-11-30"), "2026-11-30");
  const thisWeek = draftPayload({ ...d, rhythm: "this" }, "2026-11-26");
  const nextWeek = draftPayload({ ...d, rhythm: "next" }, "2026-11-26");
  assert.deepEqual([thisWeek.every, thisWeek.week_anchor, nextWeek.week_anchor], [2, "2026-11-23", "2026-11-30"]);
  const entry = (every, week_anchor) => ({
    id: 1, subject_id: 3, subject_name: "X", title: "X", kind: "exercise", kind_label: "Cvičení", room: null, weekday: 0,
    weekday_label: "pondělí", start: "09:00", end: "10:30", valid_from: "2026-10-05", valid_until: "2027-01-31",
    every, week_anchor, next_date: null, next_regular_date: null, exceptions: [],
  });
  // kotva 5. 10.: týden od 23. 11. je o 7 týdnů dál → výuka příští týden; kotva 12. 10. → tento týden
  assert.equal(draftFrom(entry(2, "2026-10-05"), "2026-11-26").rhythm, "next");
  assert.equal(draftFrom(entry(2, "2026-10-12"), "2026-11-26").rhythm, "this");
  assert.equal(draftFrom(entry(1, "2026-10-05"), "2026-11-26").rhythm, "weekly");
});
