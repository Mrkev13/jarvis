// MRK-41: ruční rozvrh – výchozí semestr, kontrola formuláře, seskupení po dnech, popisky výjimek.
import assert from "node:assert/strict";
import { test } from "node:test";

import { byWeekday, defaultSemester, draftPayload, emptyDraft, exceptionLabel, nextWeekday, validateDraft } from "./timetableLib.ts";

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
  assert.deepEqual(draftPayload({ ...d, room: "  S5 ", weekday: "2" }), {
    subject_id: 3, kind: "lecture", weekday: 2, start: "09:00", end: "10:30", room: "S5", valid_from: "2026-10-01", valid_until: "2027-01-31",
  });
  assert.equal(draftPayload({ ...d, room: " " }).room, null);
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
