/**
 * MRK-129: fokus po akci, který přežije pozdní vykreslení. Po obnovení dat React může řádek nahradit novým uzlem až
 * po prvním snímku – fokus pak spadne do `body`. `focusWithRetry` proto zkouší několik snímků, ale znovu zaměří jen
 * když fokus cíl ztratil; nikdy nepřebije prvek, který si mezitím zaměřil uživatel. Testy: focusRetry.test.mjs.
 */
export type FocusState = {
  /** Aktuálně zaměřený prvek (`document.activeElement`). */
  active: { isConnected?: boolean } | null;
  /** Prvek, který zaměřilo tohle zaměření (null = ještě nic). */
  focused: { isConnected?: boolean } | null;
  /** Je `active` tělo stránky / nic? */
  activeIsBody: boolean;
};

/** Zaměřit (znovu)? Ano, když jsme ještě nezaměřili, nebo fokus po nás skončil v body / na odpojeném uzlu. */
export function shouldRefocus({ active, focused, activeIsBody }: FocusState): boolean {
  if (focused === null) return true;
  if (active === focused && focused.isConnected !== false) return false;
  if (activeIsBody || active === null || active.isConnected === false) return true;
  return false; // uživatel mezitím zaměřil něco jiného
}

export const FOCUS_RETRY_FRAMES = 8;

/** Zkouší `find()` zaměřit až `frames` snímků; vrací se hned (bez čekání). */
export function focusWithRetry(find: () => HTMLElement | null, frames: number = FOCUS_RETRY_FRAMES): void {
  let focused: HTMLElement | null = null;
  let left = frames;
  const step = () => {
    const active = document.activeElement as HTMLElement | null;
    const activeIsBody = active === null || active === document.body;
    if (shouldRefocus({ active, focused, activeIsBody })) {
      const el = find();
      if (el) {
        el.focus();
        focused = el;
      }
    }
    if (--left > 0) window.requestAnimationFrame(step);
  };
  window.requestAnimationFrame(step);
}
