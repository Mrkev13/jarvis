// Regrese: potvrzení AI pending akce posílalo `{}` (frontend četl neexistující `action_id`,
// backend vrací `id`) → backend vracel 422 a žádnou akci nešlo z UI potvrdit; zamítnutí
// se na server vůbec neposílalo. Spuštění: `npm test` (node --test, bez dalších závislostí).
import assert from "node:assert/strict";
import { test } from "node:test";

import { confirmActionBody, normalizePendingActions, rejectActionPath } from "./pendingActions.ts";

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
