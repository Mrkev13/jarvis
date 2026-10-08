// Roadmap 4D: globální vyhledávání – česká normalizace, řazení, navigace, skupiny, výběr, nedávné.
import assert from "node:assert/strict";
import { test } from "node:test";

import { flatten, groupResults, isSearchShortcut, searchTargetFromParams, moveSelection, normalize, parseRecent, pushRecent, scoreText, searchNavigation } from "./search.ts";

test("Czech normalization keeps meaning, drops diacritics and case", () => {
  assert.equal(normalize("  Zkouška  FYZIKA "), "zkouska fyzika");
  assert.equal(normalize("Připomínka"), "pripominka");
  assert.equal(normalize("Práce"), "prace");
  assert.equal(normalize("Řídicí centrum"), "ridici centrum");
  assert.equal(normalize(null), "");
});

test("ranking: exact > prefix > word > substring > all words > other fields", () => {
  const q = "luna";
  const s = [scoreText(q, "Luna"), scoreText(q, "Luna Snow"), scoreText(q, "Captain Luna"), scoreText(q, "Kalunas"), scoreText(q, "Postava", "luna")];
  assert.deepEqual([...s].sort((a, b) => b - a), s);
  assert.ok(s.every((x) => x > 0));
  assert.ok(scoreText("snow luna", "Luna Snow") > 0);
  assert.equal(scoreText("luna", "Thor"), 0);
  // backend musí dávat stejná čísla (search_service.score_text)
  assert.deepEqual(s, [100, 85, 70, 55, 30]);
});

test("navigation: Czech names, keywords and diacritic-insensitive input", () => {
  assert.equal(searchNavigation("prace")[0].href, "/work");
  assert.equal(searchNavigation("pripominky")[0].href, "/reminders");
  // jednotné číslo bez diakritiky (dřív „pripominka" → nic)
  assert.equal(searchNavigation("pripominka")[0].href, "/reminders");
  assert.equal(searchNavigation("poznamka")[0].href, "/memory");
  assert.equal(searchNavigation("vydaj")[0].href, "/finance");
  assert.equal(searchNavigation("dashboard")[0].href, "/");
  assert.equal(searchNavigation("jarvis")[0].href, "/ai");
  assert.equal(searchNavigation("wot")[0].href, "/wot");
  assert.equal(searchNavigation("marvel")[0].href, "/mff");
  assert.equal(searchNavigation("").length, 16); // + Nastavení (MRK-18 A2), Návyky (MRK-21)
  assert.equal(searchNavigation("moduly")[0]?.href, "/settings");
  assert.equal(searchNavigation("dnes")[0].href, "/today");
  assert.equal(searchNavigation("today")[0].href, "/today");
  assert.deepEqual(searchNavigation("xyzxyz"), []);
  // název má přednost před klíčovým slovem jiné stránky
  assert.equal(searchNavigation("finance")[0].title, "Finance");
});

test("groups: best match first, only non-empty, bounded; flatten keeps display order", () => {
  const r = (id, area, score, type = "x") => ({ id, type, title: id, subtitle: "", area, href: `/${id}`, score });
  const groups = groupResults(
    [r("a", "school", 55), r("b", "mff", 100), r("c", "school", 70), r("nav", null, 60, "page"), ...Array.from({ length: 9 }, (_, i) => r(`w${i}`, "wot", 30))],
    6,
  );
  assert.deepEqual(groups.map((g) => g.label), ["Marvel FF", "Škola", "Navigace", "World of Tanks"]);
  assert.deepEqual(groups[1].results.map((x) => x.id), ["c", "a"]);
  assert.equal(groups[3].results.length, 6);
  assert.deepEqual(flatten(groups).slice(0, 3).map((x) => x.id), ["b", "c", "a"]);
});

test("keyboard selection wraps", () => {
  assert.equal(moveSelection(-1, 3, 1), 0);
  assert.equal(moveSelection(-1, 3, -1), 2);
  assert.equal(moveSelection(2, 3, 1), 0);
  assert.equal(moveSelection(0, 3, -1), 2);
  assert.equal(moveSelection(0, 0, 1), -1);
});

test("recent destinations: dedupe by href, max 5, defensive parsing", () => {
  const item = (href) => ({ id: href, type: "page", title: href, subtitle: "", area: null, href, score: 9 });
  let list = [];
  for (const h of ["/a", "/b", "/a", "/c", "/d", "/e", "/f"]) list = pushRecent(list, item(h));
  assert.deepEqual(list.map((x) => x.href), ["/f", "/e", "/d", "/c", "/a"]);
  assert.equal(list[0].score, 0);
  assert.deepEqual(parseRecent("nonsense"), []);
  assert.deepEqual(parseRecent(JSON.stringify([{ href: "https://evil", title: "x" }, { href: "/ok", title: "ok" }])).map((x) => x.href), ["/ok"]);
});

test("Ctrl+K and Cmd+K open search, other combinations do not", () => {
  const k = (o) => ({ key: "k", ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...o });
  assert.equal(isSearchShortcut(k({ ctrlKey: true })), true);
  assert.equal(isSearchShortcut(k({ metaKey: true, key: "K" })), true);
  assert.equal(isSearchShortcut(k({})), false);
  assert.equal(isSearchShortcut(k({ ctrlKey: true, shiftKey: true })), false);
  assert.equal(isSearchShortcut(k({ ctrlKey: true, altKey: true })), false);
  assert.equal(isSearchShortcut(k({ ctrlKey: true, key: "j" })), false);
});

test("deep link params map to page targets; junk is ignored", () => {
  assert.equal(searchTargetFromParams(new URLSearchParams("exam=12")), "exam-12");
  assert.equal(searchTargetFromParams(new URLSearchParams("character=3&x=1")), "character-3");
  assert.equal(searchTargetFromParams(new URLSearchParams("exam=12a")), null);
  assert.equal(searchTargetFromParams(new URLSearchParams("q=test")), null);
});
