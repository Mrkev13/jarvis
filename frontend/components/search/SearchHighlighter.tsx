"use client";

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { prefersReducedMotion } from "@/lib/motion";
import { searchTargetFromParams } from "@/lib/search";

const WAIT_MS = 4000; // data stránky se načítají – cíl hledáme krátce opakovaně
const HIGHLIGHT_MS = 2400;

function Highlighter() {
  const pathname = usePathname();
  const params = useSearchParams();
  const target = searchTargetFromParams(params);

  useEffect(() => {
    if (!target) return;
    const started = Date.now();
    let timer = 0;
    let clear = 0;
    const find = () => {
      const el = document.querySelector<HTMLElement>(`[data-search-target="${target}"]`);
      if (!el) {
        if (Date.now() - started < WAIT_MS) timer = window.setTimeout(find, 100);
        return;
      }
      el.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "-1");
      el.focus({ preventScroll: true });
      el.classList.add("search-target-active");
      clear = window.setTimeout(() => el.classList.remove("search-target-active"), HIGHLIGHT_MS);
    };
    timer = window.setTimeout(find, 50);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(clear);
    };
  }, [pathname, target]);

  return null;
}

/**
 * Odkaz z globálního vyhledávání (např. /school?exam=12): po načtení stránky najde záznam
 * s `data-search-target="exam-12"`, posune ho do středu, dá mu fokus a krátce ho zvýrazní.
 * Když záznam na stránce není (filtr, smazaný), zůstane jen otevřená stránka modulu.
 */
export function SearchHighlighter() {
  return (
    <Suspense fallback={null}>
      <Highlighter />
    </Suspense>
  );
}
