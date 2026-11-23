import { progressFillOffset } from "@/lib/motionState";
import { BAR_TONE, clampPercent, cx, progressTone, type Tone } from "@/lib/ui";

/**
 * Ukazatel průběhu (role=progressbar). Barva: akcent, 100 % zeleně, jinou sémantiku dává volající.
 * Pohyb (Roadmap 6A, kategorie „progress"): výplň se posouvá transformací (bez layout shiftu), při omezeném
 * pohybu se změní okamžitě. Číslo/text vedle pruhu a aria-valuenow zůstávají hlavní informací.
 */
export function Progress({
  value,
  label,
  tone,
  size = "md",
  className,
}: {
  value: number;
  /** Přístupný popis („Splněno 42 %" se doplní). */
  label: string;
  tone?: Tone;
  size?: "sm" | "md";
  className?: string;
}) {
  const pct = clampPercent(value);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
      // MRK-132: segmentovaný ukazatel jako na HUD (app/hud.css .hud-progress) – dílky, výplň se při vstupu „nabije"
      className={cx("hud-progress w-full overflow-hidden rounded-[2px] bg-surface-2", size === "sm" ? "h-1.5" : "h-2", className)}
    >
      <div
        className={cx("motion-progress-fill h-full w-full rounded-full", BAR_TONE[progressTone(pct, tone)])}
        style={{ ["--motion-progress-offset" as string]: progressFillOffset(pct) } as React.CSSProperties}
      />
    </div>
  );
}
