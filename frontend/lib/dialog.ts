/**
 * Čistá logika dialogů (Roadmap 4A): klávesy, past na fokus, sdílený zámek scrollu.
 * Testy: dialog.test.mjs. React část: components/ui/ConfirmDialog.tsx.
 */
export const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=hidden])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

/** Další index fokusu v pasti (Tab dopředu, Shift+Tab dozadu, s přetečením). */
export function nextFocusIndex(current: number, count: number, backwards: boolean): number {
  if (count <= 0) return -1;
  if (current < 0) return backwards ? count - 1 : 0;
  return backwards ? (current - 1 + count) % count : (current + 1) % count;
}

/** Co udělat s klávesou v otevřeném dialogu. Během odesílání se dialog nezavírá. */
export function dialogKeyAction(key: string, busy: boolean): "close" | "trap" | "none" {
  if (key === "Escape") return busy ? "none" : "close";
  if (key === "Tab") return "trap";
  return "none";
}

export function isPromiseLike(value: unknown): value is PromiseLike<unknown> {
  return typeof value === "object" && value !== null && typeof (value as { then?: unknown }).then === "function";
}

type StyleTarget = { body: { style: { overflow: string } } };

let locks = 0;
let previousOverflow = "";

/**
 * Zámek scrollu stránky s počítadlem – dialog nad otevřeným mobilním menu si navzájem nezruší zámek.
 * Vrací idempotentní uvolnění.
 */
export function lockScroll(doc: StyleTarget = document as unknown as StyleTarget): () => void {
  if (locks === 0) {
    previousOverflow = doc.body.style.overflow;
    doc.body.style.overflow = "hidden";
  }
  locks += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    locks = Math.max(0, locks - 1);
    if (locks === 0) doc.body.style.overflow = previousOverflow;
  };
}
