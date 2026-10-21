// Roadmap 4E: Rychlé přidání – pole, připravenost k uložení, zkratka, chyby z API.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canAcknowledge, FIELD_DEFS, fieldsToForm, formToFields, isQuickAddShortcut, issueField, normalizeParse,
  parseCzNumber, prepareErrors, QUICK_ADD_EXAMPLES, QUICK_ADD_KINDS, readiness,
} from "./quickAdd.ts";
import { isSearchShortcut } from "./search.ts";

const key = (k, mods = {}) => ({ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...mods });

test("shortcut: Ctrl/Cmd+Shift+K is Quick Add and never collides with Ctrl+K search", () => {
  assert.ok(isQuickAddShortcut(key("K", { ctrlKey: true, shiftKey: true })));
  assert.ok(isQuickAddShortcut(key("k", { metaKey: true, shiftKey: true })));
  assert.ok(!isQuickAddShortcut(key("k", { ctrlKey: true })));
  assert.ok(!isQuickAddShortcut(key("K", { ctrlKey: true, shiftKey: true, altKey: true })));
  assert.ok(!isQuickAddShortcut(key("k", { shiftKey: true })));
  for (const e of [key("K", { ctrlKey: true, shiftKey: true }), key("k", { ctrlKey: true })]) {
    assert.ok(!(isQuickAddShortcut(e) && isSearchShortcut(e)), "jedna klávesa = jedna akce");
  }
});

test("Czech numbers", () => {
  assert.equal(parseCzNumber("189,90"), 189.9);
  assert.equal(parseCzNumber("1 250"), 1250);
  assert.equal(parseCzNumber("1 250,5"), 1250.5);
  assert.equal(parseCzNumber(""), null);
  assert.equal(parseCzNumber("abc"), null);
});

test("fields round-trip through the form", () => {
  const form = fieldsToForm("work", { hours: 6.5, project: "Workshop", hourly_rate: 375, date: "2026-10-03" });
  assert.equal(form.hours, "6,5");
  assert.equal("sync_to_finance" in form, false, "MRK-60: práce už nenabízí zápis do Financí");
  assert.deepEqual(formToFields("work", form), {
    hours: 6.5, project: "Workshop", hourly_rate: 375, date: "2026-10-03",
  });
  const exam = formToFields("exam", fieldsToForm("exam", { title: "Test", subject_id: 3, exam_date: "2026-10-18", exam_type: "test" }));
  assert.equal(exam.subject_id, 3);
  assert.equal(formToFields("exam", fieldsToForm("exam", { subject_id: null })).subject_id, null);
});

test("every kind has required fields and an example", () => {
  for (const kind of QUICK_ADD_KINDS) {
    assert.ok(FIELD_DEFS[kind].some((d) => d.required), kind);
    assert.ok(QUICK_ADD_EXAMPLES.some((e) => e.kind === kind), kind);
  }
});

test("readiness: open question blocks save until resolved", () => {
  const form = fieldsToForm("finance", { transaction_type: "expense", amount: 820, category: "Potraviny", description: "Albert" });
  const questions = [{ field: "amount", question: "Je to 820 Kč?" }];
  const before = readiness({ kind: "finance", form, questions, resolved: new Set(), errors: [] });
  assert.equal(before.ready, false);
  assert.deepEqual(before.blockers, ["Je to 820 Kč?"]);
  assert.ok(canAcknowledge(questions[0], form));
  const after = readiness({ kind: "finance", form, questions, resolved: new Set(["amount"]), errors: [] });
  assert.equal(after.ready, true);
});

test("readiness: missing required fields and errors", () => {
  const form = fieldsToForm("exam", { title: "Test z práva", subject_id: 1, exam_date: "" });
  const r = readiness({ kind: "exam", form, questions: [{ field: "exam_date", question: "Kdy je termín?" }], resolved: new Set(), errors: [] });
  assert.equal(r.ready, false);
  assert.ok(r.blockers.includes("Doplň: termín."));
  const bad = readiness({
    kind: "work", form: fieldsToForm("work", { hours: 40, date: "2026-10-03" }), questions: [], resolved: new Set(),
    errors: [{ field: "hours", message: "Hodiny musí být mezi 0 a 24." }],
  });
  assert.equal(bad.fieldErrors.hours, "Hodiny musí být mezi 0 a 24.");
  assert.equal(bad.ready, false);
  const edited = readiness({
    kind: "work", form: fieldsToForm("work", { hours: 4, date: "2026-10-03" }), questions: [], resolved: new Set(["hours"]),
    errors: [{ field: "hours", message: "Hodiny musí být mezi 0 a 24." }],
  });
  assert.equal(edited.ready, true, "upravené pole server ověří znovu");
  const nan = readiness({ kind: "finance", form: { transaction_type: "expense", amount: "abc" }, questions: [], resolved: new Set(["amount"]), errors: [] });
  assert.equal(nan.fieldErrors.amount, "Musí to být číslo.");
});

test("school date errors map to the date field", () => {
  assert.equal(issueField("exam", "date"), "exam_date");
  assert.equal(issueField("assignment", "date"), "due_date");
  assert.equal(issueField("work", "date"), "date");
  assert.equal(issueField("reminder", "time"), "due_local");
});

test("422 errors and parse normalization are defensive", () => {
  assert.deepEqual(prepareErrors({ detail: { errors: [{ field: "hours", message: "Mimo rozsah" }] } }), [{ field: "hours", message: "Mimo rozsah" }]);
  assert.deepEqual(prepareErrors({ detail: "x" }), []);
  assert.deepEqual(prepareErrors(null), []);
  const n = normalizeParse({ kind: "goal", confidence: 0.93 });
  assert.equal(n.kind, "unknown");
  assert.equal(n.confidence, "low");
  assert.deepEqual(n.needs_input, []);
  assert.equal(normalizeParse({ kind: "finance", confidence: "high", ready: true }).ready, true);
});
