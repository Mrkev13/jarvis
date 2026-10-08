import type { IconName } from "@/lib/icons";
import { BADGE_TONE, cx, type Tone } from "@/lib/ui";
import { Icon } from "./Icon";

/**
 * Krátký stav / kategorie. Barva = význam (tone), text vždy čitelný i bez barvy.
 * Sémantika (MRK-15): success = hotovo/splněno, warning = blíží se/pozor, danger = chyba/po termínu,
 * info = informace/rozpracováno, neutral = kategorie bez významu, accent = značka (např. odznak).
 * `icon` = volitelná malá ikona před textem (stav, ne dekorace).
 */
export function StatusBadge({
  tone = "neutral",
  children,
  dot,
  icon,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  dot?: boolean;
  icon?: IconName;
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
      {icon ? <Icon name={icon} size="xs" /> : null}
      {children}
    </span>
  );
}
