import { cx } from "@/lib/ui";
import { Icon } from "./Icon";

/**
 * MRK-123: sbalitelná skupina záznamů (nativní <details>/<summary>, výchozí sbalená). Pro méně důležité seznamy, které
 * nemají překřikovat hlavní obsah (Škola: starší po termínu, hotové a uzavřené). Nadpis ≥ 44 px, ovládání Enter /
 * mezerník; globální hledání skupinu s cílem samo otevře (components/search/SearchHighlighter).
 */
export function CollapsibleGroup({
  id,
  label,
  hint,
  defaultOpen = false,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <details data-collapsible-group={id} open={defaultOpen || undefined} className={cx("group", className)}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-[var(--radius-control)] px-1 text-sm text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 [&::-webkit-details-marker]:hidden">
        <Icon name="chevron-right" size="sm" className="motion-nav-chevron group-open:rotate-90" />
        <span className="font-medium">{label}</span>
        {hint ? <span className="text-xs text-ink-faint">· {hint}</span> : null}
      </summary>
      <div className="motion-nav-reveal mt-2">{children}</div>
    </details>
  );
}
