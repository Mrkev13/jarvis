// Roadmap 4B.1: prezentační popisky – interní hodnoty → čeština, neznámé hodnoty se neztratí.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  activitySourceLabel,
  entityRefLabel,
  entityTypeLabel,
  fallbackLabel,
  fieldLabel,
  fieldValueLabel,
  financeCategoryLabel,
  memoryCategoryLabel,
} from "./labels.ts";

test("entity types from the audit log", () => {
  assert.equal(entityTypeLabel("WotGrind"), "Grind");
  assert.equal(entityTypeLabel("FinanceTransaction"), "Transakce");
  assert.equal(entityTypeLabel("WorkSession"), "Pracovní záznam");
  assert.equal(entityTypeLabel("Assignment"), "Úkol");
  assert.equal(entityTypeLabel("Reminder"), "Připomínka");
  assert.equal(entityRefLabel("WotGrind", 6), "Grind #6");
  assert.equal(entityRefLabel("Goal", null), "Cíl");
  // neznámý typ zůstává (žádné ztracené informace)
  assert.equal(entityTypeLabel("SomethingNew"), "SomethingNew");
});

test("field names", () => {
  assert.equal(fieldLabel("amount"), "Částka");
  assert.equal(fieldLabel("category"), "Kategorie");
  assert.equal(fieldLabel("due_date"), "Termín");
  assert.equal(fieldLabel("xp_remaining"), "Zbývá XP");
  assert.equal(fieldLabel("some_new_field"), "Some new field");
});

test("finance categories keep unknown values readable", () => {
  assert.equal(financeCategoryLabel("work"), "Práce");
  assert.equal(financeCategoryLabel("food"), "Jídlo");
  assert.equal(financeCategoryLabel(" Food "), "Jídlo");
  assert.equal(financeCategoryLabel("jídlo"), "Jídlo");
  assert.equal(financeCategoryLabel("Nájem"), "Nájem");
  assert.equal(financeCategoryLabel(""), "–");
});

test("memory categories", () => {
  assert.equal(memoryCategoryLabel("plan"), "Plán");
  assert.equal(memoryCategoryLabel("context"), "Kontext");
  assert.equal(memoryCategoryLabel("preference"), "Preference");
  assert.equal(memoryCategoryLabel("vlastní"), "Vlastní");
  assert.equal(fallbackLabel(null), "–");
});

test("field values in change details", () => {
  assert.equal(fieldValueLabel("status", "in_progress"), "Rozpracováno");
  assert.equal(fieldValueLabel("priority", "high"), "Vysoká");
  assert.equal(fieldValueLabel("transaction_type", "expense"), "Výdaj");
  assert.equal(fieldValueLabel("sync_to_finance", true), "Ano");
  assert.equal(fieldValueLabel("hours", 0.5), "0,5");
  assert.equal(fieldValueLabel("category", "food", "FinanceTransaction"), "Jídlo");
  assert.equal(fieldValueLabel("category", "plan", "Memory"), "Plán");
  // oblast v detailu (např. smazaná poznámka v paměti) – dřív zůstávalo „general"
  assert.equal(fieldValueLabel("area", "general", "Memory"), "Obecné");
  assert.equal(fieldValueLabel("area", "wot"), "World of Tanks");
  assert.equal(fieldValueLabel("area", "zahrada"), "Zahrada");
  assert.equal(fieldValueLabel("category", "food", "Goal"), "food");
  assert.equal(fieldValueLabel("title", "Esej"), "Esej");
  assert.equal(fieldValueLabel("title", null), "–");
});

test("AI tool names, memory AI categories and activity sources", () => {
  assert.equal(entityTypeLabel("add_work_session"), "Zápis práce");
  assert.equal(entityTypeLabel("undo_change"), "Vrácení změny");
  assert.equal(memoryCategoryLabel("decision"), "Rozhodnutí");
  assert.equal(memoryCategoryLabel("constraint"), "Omezení");
  assert.equal(activitySourceLabel("manual"), "ručně");
  assert.equal(activitySourceLabel("ai_confirm"), "AI, potvrzeno");
  assert.equal(activitySourceLabel("cron_x"), "cron_x");
});
