import { CARD_TONE, cx, type Tone } from "@/lib/ui";

/** Seznam záznamů (ul) s jednotným rozestupem. */
export function EntityList({ children, className, label }: { children: React.ReactNode; className?: string; label?: string }) {
  return (
    <ul aria-label={label} className={cx("space-y-2", className)}>
      {children}
    </ul>
  );
}

/**
 * Jeden záznam: štítky, titulek, metadata, volitelný obsah a akce.
 * `tone` jen pro řádky, které vyžadují pozornost (např. připomínka „teď"). `muted` = uzavřené.
 */
export function EntityRow({
  title,
  badges,
  meta,
  children,
  actions,
  tone = "neutral",
  muted,
  className,
  style,
  busy,
  searchTarget,
  leading,
  rowKey,
  exiting,
}: {
  title: React.ReactNode;
  badges?: React.ReactNode;
  meta?: React.ReactNode;
  children?: React.ReactNode;
  actions?: React.ReactNode;
  tone?: Tone;
  muted?: boolean;
  className?: string;
  style?: React.CSSProperties;
  busy?: boolean;
  /** Cíl odkazu z globálního vyhledávání (např. „exam-12", viz components/search/SearchHighlighter). */
  searchTarget?: string;
  /** Obrázek / ikona vlevo (např. GameImage tanku) – text zůstává hlavní. */
  leading?: React.ReactNode;
  /** MRK-126: klíč řádku pro useRowExit (fokus na souseda po zmizení). */
  rowKey?: string;
  /** MRK-126: řádek právě mizí po akci – vybledne a nejde s ním pracovat. */
  exiting?: boolean;
}) {
  return (
    <li
      style={style}
      aria-busy={busy || undefined}
      data-search-target={searchTarget}
      data-row-key={rowKey}
      data-row-exiting={exiting ? "" : undefined}
      inert={exiting || undefined}
      className={cx(
        "rounded-[var(--radius-control)] border px-3 py-3 md:px-4",
        tone === "neutral" ? "border-line-subtle bg-surface-2" : CARD_TONE[tone],
        muted && "opacity-70",
        className,
        exiting && "motion-row-exit",
      )}
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className={cx("min-w-0 flex-1", leading ? "flex items-start gap-3" : null)}>
          {leading ? <div className="shrink-0">{leading}</div> : null}
          <div className="min-w-0 flex-1">
          {badges ? <div className="mb-1.5 flex flex-wrap items-center gap-1.5">{badges}</div> : null}
          <div className={cx("break-words font-medium text-ink", muted && "line-through decoration-ink-faint")}>{title}</div>
          {meta ? <div className="mt-0.5 text-sm text-ink-muted">{meta}</div> : null}
          {children}
          </div>
        </div>
        {actions ? <div className="flex flex-wrap gap-2 md:justify-end md:shrink-0">{actions}</div> : null}
      </div>
    </li>
  );
}
