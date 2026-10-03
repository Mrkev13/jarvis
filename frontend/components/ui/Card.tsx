import { staggerStyle } from "@/lib/motion";
import { CARD_TONE, cx, type Tone } from "@/lib/ui";

type CardProps = {
  children: React.ReactNode;
  /** Barevný okraj jen pro karty, které něco hlásí (pozor, chyba, AI…). Výchozí: neutrální. */
  tone?: Tone;
  /** Vnořená (sekundární) plocha uvnitř jiné karty. */
  inset?: boolean;
  /** Bez vnitřního odsazení (např. seznam od okraje k okraji). */
  flush?: boolean;
  /** Pořadí pro postupný vstup (motion-card). */
  index?: number;
  as?: "section" | "div" | "article" | "li";
  className?: string;
} & Omit<React.HTMLAttributes<HTMLElement>, "className" | "children">;

/** Základní plocha. Čistá – HUD akcenty se přidávají jen přes HudFrame/AccentLine. */
export function Card({ children, tone = "neutral", inset, flush, index, as: Tag = "section", className, style, ...rest }: CardProps) {
  return (
    <Tag
      {...rest}
      style={index === undefined ? style : { ...staggerStyle(index), ...style }}
      className={cx(
        index === undefined ? null : "motion-card",
        "border",
        inset ? "rounded-[var(--radius-control)] border-line-subtle bg-surface-2" : cx("rounded-card shadow-card", CARD_TONE[tone]),
        flush ? null : inset ? "p-3" : "p-4 md:p-5",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/** Hlavička karty: ikona/štítek, titulek (h2/h3), akce vpravo. */
export function CardHeader({
  title,
  icon,
  actions,
  description,
  as: Heading = "h2",
}: {
  title: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  description?: React.ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <Heading className="flex items-center gap-2 text-base md:text-lg font-semibold text-ink">
          {icon ? (
            <span aria-hidden="true" className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-sm">
              {icon}
            </span>
          ) : null}
          <span className="min-w-0">{title}</span>
        </Heading>
        {description ? <p className="mt-1 text-sm text-ink-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-3 text-sm">{actions}</div> : null}
    </div>
  );
}
