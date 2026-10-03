// Roadmap 4C: AI chat – mapování API, chyby (rate limit / denní limit), druh zprávy.
import assert from "node:assert/strict";
import { test } from "node:test";

import { chatHttpFailure, chatNetworkFailure, mapConversation, messageVariant, plannerCardFrom, stripStatusSymbol, toTs } from "./aiChat.ts";

test("naive UTC timestamps from the API", () => {
  assert.equal(toTs("2026-10-11T17:00:00"), Date.UTC(2026, 9, 11, 17));
  assert.equal(mapConversation({ id: 1, title: "A", created_at: "2026-10-11T17:00:00", updated_at: "2026-10-11T18:00:00" }).updatedAt, Date.UTC(2026, 9, 11, 18));
});

test("rate limit vs daily limit vs server error", () => {
  const rate = chatHttpFailure(429, { error: "AI provider nedisponuje (Rate limit 8 000 tokenů/minutu…)", answer: "⚠️ AI provider nedisponuje…" });
  assert.equal(rate.kind, "rate_limit");
  assert.equal(rate.message, "⚠️ AI provider nedisponuje…");
  const daily = chatHttpFailure(429, { error: "AI provider má vyčerpaný denní limit", answer: "⚠️ … Denní limit se během pár sekund neobnoví" });
  assert.equal(daily.kind, "daily_limit");
  assert.match(daily.notice, /Denní limit/);
  assert.equal(chatHttpFailure(503, null).kind, "server");
  assert.match(chatHttpFailure(400, { error: "missing_message" }).message, /^⚠️ missing_message/);
  assert.equal(chatNetworkFailure("http://x").kind, "network");
});

test("planner card and message variants", () => {
  assert.equal(plannerCardFrom({ card_type: "weekly", payload: {} }).card_type, "weekly");
  assert.equal(plannerCardFrom({ card_type: "other" }), null);
  assert.equal(messageVariant({ role: "assistant", content: "✅ Hotovo" }), "success");
  assert.equal(messageVariant({ role: "assistant", content: "❌ Akce byla zrušena." }), "error");
  assert.equal(messageVariant({ role: "assistant", content: "⚠️ AI má limit" }), "warning");
  assert.equal(messageVariant({ role: "assistant", content: "Chyba potvrzení: HTTP 500" }), "error");
  assert.equal(messageVariant({ role: "user", content: "✅" }), "normal");
  assert.equal(stripStatusSymbol("✅ Hotovo – x."), "Hotovo – x.");
});
