// Roadmap 4A: jednotné čtení chyb ze serveru a JSON helper.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ApiError, apiJson, errorMessage, isAbortError, jsonBody, readErrorDetail } from "./api.ts";

const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("readErrorDetail prefers FastAPI detail, handles validation lists and HTML", async () => {
  assert.equal(await readErrorDetail(json(409, { detail: "Přehled se právě generuje." })), "Přehled se právě generuje.");
  assert.equal(await readErrorDetail(json(422, { detail: [{ msg: "field required" }] })), "field required");
  assert.match(await readErrorDetail(new Response("<html>bad gateway</html>", { status: 502 })), /HTTP 502/);
  assert.match(await readErrorDetail(json(401, {})), /Přihlášení vypršelo/);
});

test("apiJson returns data, throws ApiError with detail, passes credentials", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => { calls.push([url, init]); return json(200, { ok: 1 }); };
  assert.deepEqual(await apiJson("/x"), { ok: 1 });
  assert.equal(calls[0][1].credentials, "include");
  globalThis.fetch = async () => json(500, { detail: "Interní chyba" });
  await assert.rejects(apiJson("/x"), (e) => e instanceof ApiError && e.status === 500 && e.message === "Interní chyba");
});

test("helpers: jsonBody, abort detection, user-facing messages", () => {
  assert.deepEqual(jsonBody("POST", { a: 1 }), { method: "POST", headers: { "Content-Type": "application/json" }, body: '{"a":1}' });
  assert.deepEqual(jsonBody("DELETE"), { method: "DELETE" });
  assert.equal(isAbortError(new DOMException("x", "AbortError")), true);
  assert.equal(isAbortError(new Error("x")), false);
  assert.equal(errorMessage(new TypeError("Failed to fetch")), "Nepodařilo se spojit se serverem.");
  assert.equal(errorMessage(new ApiError(404, "Nenalezeno")), "Nenalezeno");
});
