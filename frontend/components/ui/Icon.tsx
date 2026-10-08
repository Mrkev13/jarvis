import { FILLABLE, ICON_SIZES, ICON_STROKE, ICONS, type IconName, type IconSize } from "@/lib/icons";
import { cx } from "@/lib/ui";

/**
 * Kanonická ikona (MRK-15): čárová SVG ze sady `lib/icons.ts`, barva = `currentColor` (tón dává okolí), pevná
 * velikost a tah, zarovnaná na střed řádku. Bez `label` je dekorativní (aria-hidden) – vedle ikony musí být text;
 * s `label` je to obrázek s přístupným názvem (ikona bez textu).
 */
export function Icon({
  name,
  size = "sm",
  label,
  filled,
  className,
}: {
  name: IconName;
  size?: IconSize;
  label?: string;
  /** Vyplněná varianta (jen ikony z FILLABLE, např. oblíbená hvězda). */
  filled?: boolean;
  className?: string;
}) {
  const px = ICON_SIZES[size];
  const fill = filled && FILLABLE.has(name) ? "currentColor" : "none";
  return (
    <svg
      viewBox="0 0 24 24"
      width={px}
      height={px}
      fill={fill}
      stroke="currentColor"
      strokeWidth={ICON_STROKE}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cx("inline-block shrink-0 align-[-0.125em]", className)}
      data-icon={name}
      {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true, focusable: false })}
    >
      {ICONS[name].map((s, i) => {
        if (s.t === "path") return <path key={i} d={s.d} />;
        if (s.t === "circle") return <circle key={i} cx={s.cx} cy={s.cy} r={s.r} />;
        if (s.t === "rect") return <rect key={i} x={s.x} y={s.y} width={s.w} height={s.h} rx={s.rx} />;
        return <polygon key={i} points={s.points} />;
      })}
    </svg>
  );
}

/**
 * Ikona v jemném „duotone" rámečku – hlavičky karet, rychlé akce. Akcent je tlumený (cyan 10 %), aby rámeček
 * nesoutěžil s primárním tlačítkem. `tone` jen když ikona nese stav (např. varování).
 */
export function IconTile({
  name,
  tone = "accent",
  size = "md",
  className,
}: {
  name: IconName;
  tone?: "accent" | "neutral" | "warning" | "danger" | "success";
  size?: "sm" | "md";
  className?: string;
}) {
  const TONE = {
    accent: "border-accent/25 bg-accent/10 text-accent-strong",
    neutral: "border-line bg-surface-2 text-ink-2",
    warning: "border-warning/30 bg-warning/10 text-warning",
    danger: "border-danger/30 bg-danger/10 text-danger",
    success: "border-success/30 bg-success/10 text-success",
  } as const;
  return (
    <span
      aria-hidden="true"
      data-icon-tile={name}
      className={cx("grid shrink-0 place-items-center rounded-lg border", size === "md" ? "h-8 w-8" : "h-7 w-7", TONE[tone], className)}
    >
      <Icon name={name} size={size === "md" ? "md" : "sm"} />
    </span>
  );
}
