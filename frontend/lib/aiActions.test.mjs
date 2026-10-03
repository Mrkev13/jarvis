// Roadmap 4C: karta akce AI – české popisky, žádné interní názvy, náhled změn zůstává úplný.
import assert from "node:assert/strict";
import { test } from "node:test";

import { confirmedMessage, describeAction, rejectedMessage } from "./aiActions.ts";
import { AI_WRITE_TOOLS, aiToolMeta } from "./labels.ts";
import { normalizePendingActions } from "./pendingActions.ts";

const nb = (s) => s.replace(/ /g, " ");
const RAW = /\b(add_|upsert_|update_|save_memory|modify_records|manage_reminder|undo_change|date_value|hourly_rate|subject_id)\w*/;

test("create: work session with Czech date, hours and exact earnings", () => {
  const [action] = normalizePendingActions([
    { id: 7, tool: "add_work_session", arguments: { date_value: "2026-10-02", hours: 6.5, project: "Klient XYZ", hourly_rate: 375 } },
  ]);
  const v = describeAction(action);
  assert.equal(v.title, "Přidat pracovní záznam");
  assert.equal(v.doneTitle, "Přidán pracovní záznam");
  assert.equal(v.kind, "create");
  assert.equal(v.area, "work");
  assert.deepEqual(v.fields.map((f) => f.label), ["Datum", "Projekt", "Hodiny", "Sazba"]);
  assert.equal(v.fields[0].value, "2. 10. 2026");
  assert.equal(v.fields[2].value, "6,5 h");
  assert.equal(nb(v.footer.value), "2 437,50 Kč");
  assert.equal(nb(confirmedMessage(v, false)), "✅ Přidán pracovní záznam.\n\n2. 10. 2026\nKlient XYZ\n6,5 h\n2 437,50 Kč");
});

test("create: enums are labelled, never raw", () => {
  const [a] = normalizePendingActions([
    { id: 1, tool: "add_school_assignment", arguments: { title: "Esej", subject_id: 3, priority: "high", status: "in_progress", due_date: "2026-10-14" } },
  ]);
  const text = JSON.stringify(describeAction(a));
  assert.ok(text.includes("Vysoká") && text.includes("Rozpracováno") && text.includes("14. 10. 2026"), text);
  assert.ok(!/HIGH|in_progress|"high"/.test(text), text);
  const [m] = normalizePendingActions([{ id: 2, tool: "save_memory", arguments: { area: "school", category: "plan", content: "Ráno", importance: 8 } }]);
  const mv = describeAction(m);
  assert.deepEqual(mv.fields.slice(0, 2).map((f) => f.value), ["Škola", "Plán"]);
  const [f] = normalizePendingActions([{ id: 3, tool: "add_finance_transaction", arguments: { amount: 189.9, category: "food", transaction_type: "expense" } }]);
  const fv = describeAction(f);
  assert.equal(fv.title, "Přidat výdaj");
  assert.equal(nb(fv.fields[1].value), "−189,90 Kč");
  assert.equal(fv.fields[2].value, "Jídlo");
});

test("preview: batch keeps every change, count and warnings; area from entity", () => {
  const [a] = normalizePendingActions([
    {
      id: 9,
      tool: "modify_records",
      arguments: {},
      preview: {
        kind: "delete",
        entity: "finance_transaction",
        title: "Smazat transakce",
        count: 12,
        warnings: ["Smazání nejde vrátit bez zálohy."],
        items: Array.from({ length: 12 }, (_, i) => ({ label: `Oběd ${i + 1}`, changes: [] })),
      },
    },
  ]);
  const v = describeAction(a);
  assert.equal(v.kind, "delete");
  assert.equal(v.kindTone, "danger");
  assert.equal(v.area, "finance");
  assert.equal(v.items.length, 10);
  assert.equal(v.hiddenItems, 2);
  assert.deepEqual(v.footer, { label: "Počet záznamů", value: "12" });
  assert.deepEqual(v.warnings, ["Smazání nejde vrátit bez zálohy."]);
  const [u] = normalizePendingActions([
    { id: 10, tool: "modify_records", arguments: {}, preview: { kind: "update", entity: "goal", title: "Upravit cíl", count: 1, items: [{ label: "Rezerva", changes: [{ label: "Postup", old: "10 %", new: "40 %" }] }] } },
  ]);
  const uv = describeAction(u);
  assert.deepEqual(uv.items[0].changes[0], { label: "Postup", old: "10 %", new: "40 %" });
  assert.equal(uv.footer, null);
  assert.equal(confirmedMessage(uv, true), "✅ Hotovo – Upravit cíl.\n\nRezerva");
});

test("every write tool has Czech labels; unknown tools never show internal names", () => {
  for (const tool of AI_WRITE_TOOLS) {
    const meta = aiToolMeta(tool);
    assert.ok(meta.action && meta.done && !RAW.test(meta.action + meta.done), tool);
  }
  const [x] = normalizePendingActions([{ id: 4, tool: "brand_new_tool", arguments: { due_date: "2026-10-03", hourly_rate: 200, nested: { a: 1 } } }]);
  const v = describeAction(x);
  assert.equal(v.title, "Akce AI");
  assert.deepEqual(v.fields.map((f) => f.label), ["Termín", "Hodinová sazba"]);
  assert.ok(!RAW.test(JSON.stringify(v)), JSON.stringify(v));
  assert.equal(rejectedMessage(v), "❌ Akce byla zrušena: Akce AI.");
});
