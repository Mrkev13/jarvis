"use client";

import Link from "next/link";

import { Card, CardHeader } from "@/components/ui";
import { useModuleAccess } from "@/hooks/useModules";
import { askHref, suggestionsFor, type SuggestionSurface } from "@/lib/aiSuggestions";

/**
 * MRK-81: „Zeptej se Jarvise" na stránce modulu – 2–4 hotové otázky, které otevřou chat s předvyplněným dotazem
 * (neodesílá se sám). Vypnutý modul / modul bez AI = nic se neukáže.
 */
export function AskJarvis({ surface }: { surface: SuggestionSurface }) {
  const { access } = useModuleAccess();
  const items = suggestionsFor(surface, access, 4);
  if (!items.length) return null;
  return (
    <Card as="section" aria-labelledby={`ask-jarvis-${surface}`} data-ask-jarvis={surface}>
      <CardHeader as="h2" title={<span id={`ask-jarvis-${surface}`}>Zeptej se Jarvise</span>} description="Otevře chat s hotovou otázkou – stačí odeslat." />
      <ul className="mt-2 flex flex-wrap gap-2">
        {items.map((s) => (
          <li key={s.prompt}>
            <Link
              href={askHref(s.prompt)}
              className="motion-press inline-flex min-h-11 items-center rounded-full border border-line bg-surface px-3.5 py-2 text-sm text-ink-2 transition-colors hover:border-accent/40 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              {s.prompt}
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}
