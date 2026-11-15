// Škola: popisky, dny do termínu (bez posunu pásma), řazení termínů.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assignmentStatusMeta,
  creditsLabel,
  daysUntil,
  deadlineMeta,
  examStatusMeta,
  examTypeLabel,
  isDoneStatus,
  isExamClosed,
  sortByDate,
} from "./school.ts";

test("daysUntil counts calendar days from the local date", () => {
  const today = new Date(2026, 9, 3, 23, 30); // 3. 10. 2026 pozdě večer místního času
  assert.equal(daysUntil("2026-10-03", today), 0);
  assert.equal(daysUntil("2026-10-04", today), 1);
  assert.equal(daysUntil("2026-10-06", today), 3);
  assert.equal(daysUntil("2026-10-02", today), -1);
  assert.equal(daysUntil("2026-09-25", today), -8);
  assert.equal(daysUntil(null, today), null);
  assert.equal(daysUntil("", today), null);
  assert.equal(daysUntil("nesmysl", today), null);
});

test("daysUntil is not shifted across DST changes", () => {
  const beforeWinter = new Date(2026, 9, 24, 0, 5); // den před přechodem na zimní čas
  assert.equal(daysUntil("2026-10-26", beforeWinter), 2);
  const beforeSummer = new Date(2026, 2, 28, 23, 59);
  assert.equal(daysUntil("2026-03-30", beforeSummer), 2);
});

test("deadlineMeta marks overdue and soon deadlines", () => {
  assert.deepEqual(deadlineMeta(-2, "assignment"), { tone: "danger", prefix: "Po termínu", overdue: true });
  assert.deepEqual(deadlineMeta(-2, "exam"), { tone: "warning", prefix: "Proběhlo", overdue: true });
  assert.equal(deadlineMeta(0, "assignment").tone, "warning");
  assert.equal(deadlineMeta(3, "exam").tone, "warning");
  assert.equal(deadlineMeta(4, "exam").tone, "neutral");
  assert.equal(deadlineMeta(null, "assignment").tone, "neutral");
  assert.deepEqual(deadlineMeta(-5, "assignment", true), { tone: "neutral", prefix: null, overdue: false });
});

test("status and type labels are Czech", () => {
  assert.deepEqual(assignmentStatusMeta("done"), { label: "Hotovo", tone: "success" });
  assert.equal(assignmentStatusMeta("in_progress").label, "Rozpracováno");
  assert.equal(assignmentStatusMeta("todo").label, "K vypracování");
  assert.equal(assignmentStatusMeta("weird").label, "weird");
  assert.equal(examStatusMeta("upcoming").label, "Nadcházející");
  assert.deepEqual(examStatusMeta("failed"), { label: "Nesplněno", tone: "danger" });
  assert.equal(examTypeLabel("oral"), "Ústní zkouška");
  assert.equal(examTypeLabel("custom"), "custom");
  assert.ok(isDoneStatus("DONE"));
  assert.ok(!isDoneStatus("todo"));
  assert.ok(isExamClosed("failed"));
  assert.ok(!isExamClosed("upcoming"));
});

test("sortByDate puts missing dates last and keeps order on ties", () => {
  const items = [
    { id: 1, d: "2026-10-14" },
    { id: 2, d: null },
    { id: 3, d: "2026-10-02" },
    { id: 4, d: "2026-10-14" },
  ];
  assert.deepEqual(sortByDate(items, (x) => x.d).map((x) => x.id), [3, 1, 4, 2]);
  assert.deepEqual(sortByDate(items, (x) => x.d, true).map((x) => x.id), [1, 4, 3, 2]);
});

test("creditsLabel uses Czech plural", () => {
  assert.equal(creditsLabel(1), "1 kredit");
  assert.equal(creditsLabel(3), "3 kredity");
  assert.equal(creditsLabel(5), "5 kreditů");
});

// MRK-14: uzavření zkoušky, volitelný výsledek, stav „Uzavřeno"
import { emptyCloseDraft, examCloseBody, examResultLabel, isExamClosed as closedExam, examStatusMeta as examMeta } from "./school.ts";

test("closed exam status (no grade) counts as closed", () => {
  assert.equal(closedExam("closed"), true);
  assert.equal(closedExam("upcoming"), false);
  assert.deepEqual(examMeta("closed"), { label: "Uzavřeno", tone: "neutral" });
});

test("examCloseBody: result is optional, validated like the backend", () => {
  assert.deepEqual(examCloseBody(emptyCloseDraft()), { ok: true, body: { outcome: "passed", result_type: null, result_value: null } });
  assert.deepEqual(examCloseBody({ outcome: "passed", result_type: "percent", result_value: " 87,5 " }).body, { outcome: "passed", result_type: "percent", result_value: "87,5" });
  assert.equal(examCloseBody({ outcome: "passed", result_type: "points", result_value: "42 / 50" }).ok, true);
  assert.equal(examCloseBody({ outcome: "failed", result_type: "grade", result_value: "F" }).ok, true);
  assert.deepEqual(examCloseBody({ outcome: "failed", result_type: "pass_fail", result_value: "x" }).body, { outcome: "failed", result_type: "pass_fail", result_value: null });
  assert.equal(examCloseBody({ outcome: "closed", result_type: "pass_fail", result_value: "" }).ok, false);
  assert.match(examCloseBody({ outcome: "passed", result_type: "percent", result_value: "120" }).error, /0–100/);
  assert.match(examCloseBody({ outcome: "passed", result_type: "points", result_value: "hodně" }).error, /Body/);
  assert.match(examCloseBody({ outcome: "passed", result_type: "grade", result_value: "7" }).error, /Známka/);
  assert.match(examCloseBody({ outcome: "passed", result_type: "grade", result_value: "" }).error, /Vyplň/);
});

test("examResultLabel", () => {
  assert.equal(examResultLabel("percent", "87,5"), "87,5 %");
  assert.equal(examResultLabel("points", "42/50"), "42/50 b");
  assert.equal(examResultLabel("grade", "2-"), "známka 2-");
  assert.equal(examResultLabel("pass_fail", "passed"), null);
  assert.equal(examResultLabel(null, null), null);
});

// MRK-75: archivované předměty se nenabízejí, úprava posílá jen změněná pole
test("offeredSubjects a visibleSubjects skrývají archivované", async () => {
  const { offeredSubjects, visibleSubjects } = await import("./school.ts");
  const subjects = [
    { id: 1, name: "Právo", code: "", semester: "", credits: 0, active: false },
    { id: 2, name: "Angličtina", code: "", semester: "", credits: 0, active: true },
  ];
  assert.deepEqual(offeredSubjects(subjects).map((s) => s.id), [2]);
  assert.deepEqual(offeredSubjects([{ id: 3, name: "Bez příznaku" }]).map((s) => s.id), [3]);
  assert.deepEqual(visibleSubjects(subjects, false).map((s) => s.id), [2]);
  assert.deepEqual(visibleSubjects(subjects, true).map((s) => s.id), [2, 1]);
});

test("subjectPatch posílá jen změny a odmítne neplatný formulář", async () => {
  const { subjectDraftFrom, subjectPatch } = await import("./school.ts");
  const s = { id: 1, name: "Právo", code: "PRA", semester: "ZS", credits: 5, active: true };
  assert.deepEqual(subjectPatch(s, subjectDraftFrom(s)), {});
  assert.deepEqual(subjectPatch(s, { ...subjectDraftFrom(s), name: " Právo I ", credits: "6" }), { name: "Právo I", credits: 6 });
  assert.deepEqual(subjectPatch(s, { ...subjectDraftFrom(s), credits: "" }), { credits: 0 });
  assert.equal(subjectPatch(s, { ...subjectDraftFrom(s), name: "  " }), null);
  assert.equal(subjectPatch(s, { ...subjectDraftFrom(s), credits: "100" }), null);
  assert.equal(subjectPatch(s, { ...subjectDraftFrom(s), credits: "2.5" }), null);
});

// MRK-76: Moodle termíny – jen platné položky s odkazem do Kalendáře
test("moodleDeadlines bere jen platné položky", async () => {
  const { moodleDeadlines } = await import("./school.ts");
  const ok = { key: "7", event_id: 7, title: "Test 1", date: "2026-10-14", time: "22:00", all_day: false,
    subject_id: 1, subject_name: "Právo", href: "/calendar?event=7" };
  assert.deepEqual(moodleDeadlines({ items: [ok, { ...ok, href: "https://evil" }, null, { title: 1 }] }), [ok]);
  assert.deepEqual(moodleDeadlines({ items: [], calendar_enabled: false }), []);
  assert.deepEqual(moodleDeadlines(null), []);
  assert.deepEqual(moodleDeadlines("x"), []);
});
