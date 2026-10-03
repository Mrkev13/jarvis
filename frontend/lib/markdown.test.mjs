// Roadmap 4C: Markdown odpovědí AI – stejné chování jako dřív, teď testovatelné.
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseInline, parseMarkdown, tryParsePlan } from "./markdown.ts";

test("blocks: headings, paragraphs joined, lists, code", () => {
  const blocks = parseMarkdown("# Plán\nPrvní řádek\npokračuje\n\n- a\n- **b**\n1. jedna\n2. dvě\n```py\nx = 1\n```");
  assert.deepEqual(blocks.map((b) => b.type), ["heading", "paragraph", "list", "list", "code"]);
  assert.equal(blocks[0].level, 1);
  assert.equal(blocks[1].content[0].text, "První řádek pokračuje");
  assert.equal(blocks[2].ordered, false);
  assert.equal(blocks[2].items[1][0].type, "strong");
  assert.equal(blocks[3].ordered, true);
  assert.deepEqual(blocks[4], { type: "code", lang: "py", text: "x = 1" });
});

test("inline: code, strong, em (both syntaxes)", () => {
  assert.deepEqual(parseInline("a `x` **b** *c* _d_").map((t) => t.type), ["text", "code", "text", "strong", "text", "em", "text", "em"]);
  assert.equal(parseInline("**tučně _a_ dál**")[0].children[1].type, "em");
});

test("legacy JSON weekly plan becomes a plan block; other JSON stays code", () => {
  const plan = { summary: "Týden", actions: [{ priority: 1, area: "school", title: "Esej", reason: "Termín" }] };
  const [b] = parseMarkdown("```json\n" + JSON.stringify(plan) + "\n```");
  assert.equal(b.type, "plan");
  assert.equal(b.actions[0].title, "Esej");
  assert.equal(parseMarkdown('```json\n{"a":1}\n```')[0].type, "code");
  assert.equal(tryParsePlan('{"summary":"x","actions":[]}'), null);
});
