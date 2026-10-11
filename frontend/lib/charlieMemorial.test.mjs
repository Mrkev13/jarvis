import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);

function findElement(node, predicate) {
  if (!React.isValidElement(node)) return null;
  if (predicate(node)) return node;
  for (const child of React.Children.toArray(node.props.children)) {
    const found = findElement(child, predicate);
    if (found) return found;
  }
  return null;
}

function loadMemorial() {
  const source = readFileSync(new URL("../components/CharlieMemorial.tsx", import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  const mod = { exports: {} };
  new Function("require", "module", "exports", compiled)(
    (name) => {
      if (name === "next/image") return { default: (props) => React.createElement("img", props) };
      if (name === "@/components/ui/Icon") return { Icon: () => React.createElement("svg", { "data-icon": "paw" }) };
      if (name === "@/components/ui/useModal") return { useModal: () => undefined };
      return require(name);
    },
    mod,
    mod.exports,
  );
  return mod.exports;
}

test("the subtle Charlie paw is an accessible dialog trigger", () => {
  const { CharlieMemorialButton } = loadMemorial();
  let opened = false;
  const button = CharlieMemorialButton({ onOpen: () => { opened = true; } });
  const html = renderToStaticMarkup(button);

  assert.match(html, /title="Charlie"/);
  assert.match(html, /aria-label="Charlie"/);
  assert.match(html, /aria-haspopup="dialog"/);
  assert.match(html, /data-icon="paw"/);
  button.props.onClick();
  assert.equal(opened, true);
});

test("the memorial panel keeps the full local photo and exact copy", () => {
  const { CharlieMemorialPanel } = loadMemorial();
  const panel = CharlieMemorialPanel({ onClose: () => undefined, panelRef: { current: null } });
  const html = renderToStaticMarkup(panel);

  assert.match(html, /role="dialog"/);
  assert.match(html, /aria-modal="true"/);
  assert.match(html, />Charlie</);
  assert.match(html, /Pořád součást Hubu\./);
  assert.match(html, /src="\/charlie-memorial\.jpg"/);
  assert.match(html, /alt="Charlie"/);
  assert.match(html, /object-contain/);
});

test("X and backdrop close the memorial without treating panel clicks as outside clicks", () => {
  const { CharlieMemorialPanel } = loadMemorial();
  let closes = 0;
  const panel = CharlieMemorialPanel({ onClose: () => { closes += 1; }, panelRef: { current: null } });
  const backdrop = panel;
  const closeButton = findElement(panel, (node) => node.type === "button" && node.props["aria-label"] === "Zavřít");
  assert.ok(closeButton, "the visible X close button must be present");

  closeButton.props.onClick();
  assert.equal(closes, 1);

  const outside = {};
  backdrop.props.onMouseDown({ target: outside, currentTarget: outside, preventDefault() {} });
  assert.equal(closes, 2);

  backdrop.props.onMouseDown({ target: {}, currentTarget: outside, preventDefault() {} });
  assert.equal(closes, 2);
});
