import { areaMeta } from "@/lib/areas";
import { cx } from "@/lib/ui";

/** Štítek oblasti (Škola, Finance…) – barva = identita oblasti, ne stav. */
export function AreaBadge({ area, className }: { area: string | null | undefined; className?: string }) {
  const meta = areaMeta(area);
  return (
    <span
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4",
        meta.bg,
        meta.border,
        meta.text,
        className,
      )}
    >
      {meta.label}
    </span>
  );
}
