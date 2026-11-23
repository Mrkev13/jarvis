import { MAIN_CONTENT_ID } from "@/lib/shell";
import { cx } from "@/lib/ui";

/** Obsah stránky: jednotná šířka, okraje a rozestupy sekcí. */
export function ContentContainer({
  children,
  width = "default",
  className,
}: {
  children: React.ReactNode;
  width?: "default" | "narrow";
  className?: string;
}) {
  return (
    <main
      id={MAIN_CONTENT_ID}
      tabIndex={-1}
      className={cx(
        "mx-auto w-full focus:outline-none px-4 py-5 md:px-8 md:py-8 space-y-6 md:space-y-8",
        width === "narrow" ? "max-w-[var(--page-max-narrow)]" : "max-w-[var(--page-max)]",
        className,
      )}
    >
      {children}
    </main>
  );
}

/** Hlavička stránky: volitelný technický štítek, h1, jednořádkový popis, akce vpravo (na mobilu pod). */
export function PageHeader({
  title,
  subtitle,
  eyebrow,
  actions,
  mobileActions,
  meta,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  /** HUD štítek nad nadpisem („Modul · škola") – MRK-125: má ho každá stránka. */
  eyebrow?: React.ReactNode;
  actions?: React.ReactNode;
  /**
   * MRK-125: náhrada `actions` na úzkém displeji (< sm) – typicky menu ⋯ vedle nadpisu, aby řádek tlačítek
   * nezabral první obrazovku. Od sm se ukazují `actions`.
   */
  mobileActions?: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <header data-page-header="" className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0 flex-1">
        {eyebrow ? <div data-page-hud="" className="mb-2">{eyebrow}</div> : null}
        <div className="flex items-start justify-between gap-3">
          <h1 className="min-w-0 font-display text-2xl md:text-[2rem] font-semibold tracking-wide text-ink">
            {title}
            {/* MRK-131: světelná linka pod titulkem – při vstupu stránky se dokreslí */}
            <span aria-hidden="true" className="page-title-rule" />
          </h1>
          {mobileActions ? <div data-page-mobile-actions="" className="shrink-0 sm:hidden">{mobileActions}</div> : null}
        </div>
        {subtitle ? <p className="mt-1.5 text-sm md:text-base text-ink-muted">{subtitle}</p> : null}
        {meta ? <div className="mt-1.5 text-xs text-ink-muted">{meta}</div> : null}
      </div>
      {actions ? <div className={cx("flex flex-wrap gap-2 sm:justify-end", mobileActions ? "hidden sm:flex" : null)}>{actions}</div> : null}
    </header>
  );
}

/** Hlavička sekce (h2) s volitelným popisem a akcí. */
export function SectionHeader({
  title,
  description,
  actions,
  id,
  as: Heading = "h2",
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  id?: string;
  as?: "h2" | "h3";
}) {
  return (
    <div className="flex items-start justify-between gap-3 flex-wrap">
      <div className="min-w-0">
        <Heading id={id} className={cx("font-semibold text-ink", Heading === "h2" ? "text-lg" : "text-base")}>
          {title}
        </Heading>
        {description ? <p className="mt-0.5 text-sm text-ink-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2 shrink-0">{actions}</div> : null}
    </div>
  );
}

/** Sekce stránky: hlavička + obsah s jednotným rozestupem. */
export function PageSection({
  title,
  description,
  actions,
  children,
  className,
  labelledBy,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  labelledBy?: string;
}) {
  return (
    <section className={cx("space-y-3", className)} aria-labelledby={labelledBy}>
      {title ? <SectionHeader id={labelledBy} title={title} description={description} actions={actions} /> : null}
      {children}
    </section>
  );
}
