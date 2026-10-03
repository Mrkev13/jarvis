// Regrese: potvrzení AI pending akce posílalo `{}` (frontend četl neexistující `action_id`,
// backend vrací `id`) → backend vracel 422 a žádnou akci nešlo z UI potvrdit; zamítnutí
// se na server vůbec neposílalo. Spuštění: `npm test` (node --test, bez dalších závislostí).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  confirmActionBody,
  describePreview,
  isUndoAvailable,
  normalizePendingActions,
  normalizePreview,
  outcomeMotionClass,
  rejectActionPath,
  UNDO_PATH,
  undoActionBody,
} from "./pendingActions.ts";

// Přesný tvar položky z backendu: backend/ai.py `_run_tool_calls` → pending_actions.append({...}).
const backendPendingAction = {
  id: "42",
  tool: "add_finance_transaction",
  arguments: { amount: 300, category: "Jídlo", transaction_type: "expense", description: "oběd" },
  expires_at: "2026-10-03T12:30:00",
};

test("normalizes the backend pending action shape and keeps its id", () => {
  const [action] = normalizePendingActions([backendPendingAction]);
  assert.equal(action.id, "42");
  assert.equal(action.tool, "add_finance_transaction");
  assert.deepEqual(action.arguments, backendPendingAction.arguments);
});

test("confirm request sends the backend id as action_id and is never {}", () => {
  const [action] = normalizePendingActions([backendPendingAction]);
  const body = JSON.stringify(confirmActionBody(action));
  assert.equal(body, '{"action_id":"42"}');
  assert.notEqual(body, "{}");
});

test("reject uses the same id as confirm", () => {
  const [action] = normalizePendingActions([backendPendingAction]);
  assert.equal(rejectActionPath(action), "/ai/reject/42");
  assert.equal(rejectActionPath(action).split("/").pop(), confirmActionBody(action).action_id);
});

test("numeric ids are accepted and sent as strings (backend ConfirmActionRequest.action_id: str)", () => {
  const [action] = normalizePendingActions([{ ...backendPendingAction, id: 7 }]);
  assert.deepEqual(confirmActionBody(action), { action_id: "7" });
  assert.equal(rejectActionPath(action), "/ai/reject/7");
});

test("items without a usable id are dropped instead of producing an empty confirm body", () => {
  const legacy = { action_id: "9", tool: "add_work_session", arguments: {} }; // starý (chybný) frontend tvar
  const actions = normalizePendingActions([legacy, { ...backendPendingAction, id: "" }, null, "x", backendPendingAction]);
  assert.deepEqual(actions.map((a) => a.id), ["42"]);
});

test("non-array payloads yield no actions", () => {
  assert.deepEqual(normalizePendingActions(undefined), []);
  assert.deepEqual(normalizePendingActions({ id: "1" }), []);
});

test("ids are URL-encoded in the reject path", () => {
  assert.equal(rejectActionPath({ id: "a/b", tool: "t", arguments: {} }), "/ai/reject/a%2Fb");
});

test("building a request for an action without id throws instead of sending {}", () => {
  assert.throws(() => confirmActionBody({ id: "", tool: "t", arguments: {} }));
  assert.throws(() => rejectActionPath({ id: "", tool: "t", arguments: {} }));
});

// ===== Phase B: úpravy / mazání / dokončení s náhledem z backendu =====
const backendPreview = {
  kind: "update",
  entity: "finance_transaction",
  title: "Upravit: transakce",
  count: 1,
  items: [{ id: 5, label: "−320 Kč Jídlo (oběd s kolegy) · 2. 10. 2026", changes: [
    { field: "amount", label: "Částka", old: "320 Kč", new: "450 Kč" },
  ] }],
  warnings: [],
};
const modifyAction = {
  id: "77",
  tool: "modify_records",
  arguments: { plan: { version: 1, preview: backendPreview } },
  preview: backendPreview,
  expires_at: null,
};

test("modify_records keeps the backend preview and the same confirm/reject id contract", () => {
  const [action] = normalizePendingActions([modifyAction]);
  assert.equal(action.preview.title, "Upravit: transakce");
  assert.deepEqual(confirmActionBody(action), { action_id: "77" });
  assert.equal(rejectActionPath(action), "/ai/reject/77");
});

test("preview falls back to the stored plan when the item has no top-level preview", () => {
  const withoutTopLevel = { ...modifyAction };
  delete withoutTopLevel.preview;
  const [action] = normalizePendingActions([withoutTopLevel]);
  assert.equal(action.preview.count, 1);
});

test("create actions have no preview (per-tool cards stay unchanged)", () => {
  const [action] = normalizePendingActions([backendPendingAction]);
  assert.equal(action.preview, null);
});

test("edit card shows target and old -> new value", () => {
  const info = describePreview(normalizePreview(backendPreview));
  assert.equal(info.title, "Upravit: transakce");
  assert.deepEqual(info.fields, [
    { label: "Akce", value: "Úprava" },
    { label: "Záznam", value: "−320 Kč Jídlo (oběd s kolegy) · 2. 10. 2026" },
    { label: "Částka", value: "320 Kč → 450 Kč" },
  ]);
  assert.equal(info.footer, null);
});

test("delete card shows the record and a count", () => {
  const info = describePreview(normalizePreview({
    kind: "delete", title: "Smazat: transakce", count: 1,
    items: [{ label: "−1 Kč Ostatní (testovací výdaj)", changes: [] }], warnings: ["Navázaný příjem zůstane."],
  }));
  assert.equal(info.fields[0].value, "Smazání");
  assert.equal(info.fields[1].value, "−1 Kč Ostatní (testovací výdaj)");
  assert.deepEqual(info.fields[2], { label: "Upozornění", value: "Navázaný příjem zůstane." });
  assert.deepEqual(info.footer, { label: "Počet záznamů", value: "1" });
});

test("batch card lists every affected record and the count", () => {
  const items = Array.from({ length: 12 }, (_, i) => ({ label: `Úkol ${i + 1}`, changes: [] }));
  const info = describePreview(normalizePreview({ kind: "complete", title: "Označit jako hotové: 12× úkol", count: 12, items }));
  assert.deepEqual(info.footer, { label: "Počet záznamů", value: "12" });
  assert.equal(info.fields.filter((f) => /^\d+\.$/.test(f.label)).length, 10);
  assert.deepEqual(info.fields.at(-1), { label: "…", value: "a dalších 2" });
});

test("malformed previews are ignored instead of crashing the card", () => {
  assert.equal(normalizePreview({ title: 5, items: [] }), null);
  assert.equal(normalizePreview(null, { plan: "x" }), null);
});

// ===== Phase C: vrácení potvrzené změny =====
test("undo is offered only when the backend says the confirmed action is reversible", () => {
  assert.equal(isUndoAvailable({ ok: true, result: { undo_available: true } }), true);
  assert.equal(isUndoAvailable({ ok: true, result: { undo_available: false } }), false);
  assert.equal(isUndoAvailable({ ok: true, result: { id: 5 } }), false); // create akce
  assert.equal(isUndoAvailable({ ok: false, result: { undo_available: true } }), false);
  assert.equal(isUndoAvailable(null), false);
});

test("undo request sends the executed action id and never {}", () => {
  assert.equal(UNDO_PATH, "/actions/undo");
  assert.deepEqual(undoActionBody("77"), { action_id: "77" });
  assert.throws(() => undoActionBody(""));
});

test("undo pending card renders through the generic preview", () => {
  const [action] = normalizePendingActions([{
    id: "90",
    tool: "undo_change",
    arguments: { plan: { version: 1, kind: "undo", original_action_id: 77 } },
    preview: {
      kind: "undo", title: "Vrátit: Upravit: transakce", count: 1,
      items: [{ label: "−450 Kč Jídlo (oběd)", changes: [{ label: "Částka", old: "450 Kč", new: "300 Kč" }] }],
      warnings: [],
    },
  }]);
  const info = describePreview(action.preview);
  assert.deepEqual(info.fields.slice(0, 3), [
    { label: "Akce", value: "Vrácení změny" },
    { label: "Záznam", value: "−450 Kč Jídlo (oběd)" },
    { label: "Částka", value: "450 Kč → 300 Kč" },
  ]);
  assert.deepEqual(confirmActionBody(action), { action_id: "90" });
  assert.equal(rejectActionPath(action), "/ai/reject/90");
});

// Regrese (live Phase C A/C): „Vrátit" byl uvnitř .motion-outcome (pointer-events: none + fade-out za 1,6 s)
// → tlačítko zmizelo po pár sekundách a nešlo na něj kliknout, přestože nabídka měla trvat 20 s.
test("outcomes offering undo use a persistent, clickable motion class", () => {
  assert.equal(outcomeMotionClass("16"), "motion-outcome-undo");
  assert.equal(outcomeMotionClass(undefined), "motion-outcome");
  assert.equal(outcomeMotionClass(""), "motion-outcome");
});

test("the undo outcome CSS neither fades out nor blocks clicks", () => {
  const css = readFileSync(new URL("../app/motion.css", import.meta.url), "utf8");
  const rules = [...css.matchAll(/\.motion-outcome-undo\s*\{([^}]*)\}/g)].map((m) => m[1]);
  assert.ok(rules.length >= 1, "chybí pravidlo .motion-outcome-undo");
  for (const body of rules) {
    assert.ok(!body.includes("motion-fade-out"), "undo karta nesmí po chvíli zmizet");
    assert.ok(!/pointer-events:\s*none/.test(body), "Vrátit musí jít kliknout");
  }
  assert.match(rules[0], /pointer-events:\s*auto/);
});
