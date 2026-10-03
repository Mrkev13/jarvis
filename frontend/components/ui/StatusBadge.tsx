import { BADGE_TONE, cx, type Tone } from "@/lib/ui";

/** Krátký stav / kategorie. Barva = význam (tone), text vždy čitelný i bez barvy. */
export function StatusBadge({
  tone = "neutral",
  children,
  dot,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        BADGE_TONE[tone],
        className,
      )}
    >
      {dot ? <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}
