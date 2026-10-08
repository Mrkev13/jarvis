// MRK-15: sada čárových ikon a hlídání, že převedené obrazovky nevrací funkční emoji.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { FILLABLE, ICON_NAMES, ICON_SIZES, ICON_STROKE, ICONS, isIconName } from "./icons.ts";

test("every icon has drawable shapes on the 24 grid", () => {
  assert.ok(ICON_NAMES.length >= 20);
  for (const name of ICON_NAMES) {
    assert.match(name, /^[a-z]+(-[a-z]+)*$/, name);
    assert.ok(ICONS[name].length > 0, name);
    for (const s of ICONS[name]) {
      if (s.t === "path") assert.match(s.d, /^M[\d.\s,a-zA-Z-]+$/, name);
      if (s.t === "circle") assert.ok(s.cx >= 0 && s.cx <= 24 && s.r > 0, name);
      if (s.t === "rect") assert.ok(s.x >= 0 && s.x + s.w <= 24 && s.y + s.h <= 24, name);
    }
  }
});

test("tokens: sizes, stroke, fillable, name guard", () => {
  assert.deepEqual(ICON_SIZES, { xs: 12, sm: 16, md: 20, lg: 24 });
  assert.equal(ICON_STROKE, 1.75);
  assert.ok(FILLABLE.has("star"));
  assert.equal(isIconName("calendar"), true);
  assert.equal(isIconName("📅"), false);
  assert.equal(isIconName("toString"), false, "žádné zděděné klíče");
  assert.equal(isIconName(undefined), false);
});

const PICTOGRAPH = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}]/u;
test("migrated screens use icons, not functional emoji", () => {
  for (const file of ["../components/dashboard/widgets.tsx", "../app/page.tsx", "../app/today/page.tsx", "../components/WeeklyReviewCard.tsx",
    "../components/NotificationsBell.tsx", "../components/wot/MilestoneCard.tsx", "../components/wot/replays/ReplayRow.tsx"]) {
    const code = readFileSync(new URL(file, import.meta.url), "utf8")
      .split("\n")
      .filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l))
      .join("\n");
    assert.equal(PICTOGRAPH.test(code), false, `${file} obsahuje emoji`);
  }
});
