import { HudLabel } from "@/components/ui";

const SUGGESTIONS = [
  "Co mám dnes dělat?",
  "Jaký mám plán na tento týden?",
  "Jak si vedu s plněním cílů?",
  "Kolik zbývá XP na VZ.55?",
  "Jaká je moje aktuální finanční bilance?",
];

/** Prázdná konverzace: krátké představení a návrhy otázek (vloží se do pole, neodesílají se samy). */
export function EmptyConversation({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start py-6 md:py-10">
      <HudLabel className="flex items-center gap-2">
        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent-2 shadow-[0_0_8px_rgb(167_139_250/0.7)]" />
        Standa AI
      </HudLabel>
      <h2 className="mt-2 text-xl font-semibold text-ink">Na co se chceš zeptat?</h2>
      <p className="mt-1.5 text-sm leading-6 text-ink-muted">
        Vidím tvoje úkoly a zkoušky, práci, finance, cíle, připomínky, paměť i hry. Změny jen navrhuji – provedou se, až je potvrdíš.
      </p>
      <ul className="mt-5 grid w-full gap-2 sm:grid-cols-2" aria-label="Návrhy otázek">
        {SUGGESTIONS.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => onPick(s)}
              className="motion-press flex min-h-11 w-full items-center rounded-[var(--radius-control)] border border-line bg-surface px-3.5 py-2.5 text-left text-sm text-ink-2 transition-colors hover:border-accent/40 hover:bg-surface-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
