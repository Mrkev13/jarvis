import { useId } from "react";
import { cx } from "@/lib/ui";

/**
 * MRK-131: znak Standa Hubu – arc reaktor (Jarvis). Čisté SVG bez obrázků:
 * vnější prstenec, segmentovaný prstenec (pomalu se otáčí), vnitřní prstenec s cívkami (protiběžně),
 * trojúhelníkové jádro a zářící střed. Otáčení jen přes transform; při omezeném pohybu stojí (app/hud.css).
 *
 * `live` = otáčí se (znak v menu, start systému); bez něj statický (malé ikony, tisk).
 */
export function ArcReactor({
  size = 32,
  live = true,
  className,
}: {
  size?: number;
  live?: boolean;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const core = `arc-core-${id}`;
  const glow = `arc-glow-${id}`;
  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      data-arc-reactor=""
      className={cx("arc-reactor", live && "arc-reactor-live", className)}
    >
      <defs>
        <radialGradient id={core}>
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="35%" stopColor="rgb(var(--arc-strong-rgb))" />
          <stop offset="100%" stopColor="rgb(var(--arc-rgb))" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={glow}>
          <stop offset="0%" stopColor="rgb(var(--arc-rgb))" stopOpacity="0.45" />
          <stop offset="100%" stopColor="rgb(var(--arc-rgb))" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="50" cy="50" r="49" fill={`url(#${glow})`} />
      <circle cx="50" cy="50" r="45" fill="none" stroke="rgb(var(--arc-rgb) / 0.45)" strokeWidth="1.5" />
      {/* segmenty: 12 dílků po 30°, mezera 6° */}
      <g className="arc-ring-outer">
        <circle
          cx="50" cy="50" r="38" fill="none" stroke="rgb(var(--arc-rgb) / 0.85)" strokeWidth="6"
          pathLength="360" strokeDasharray="24 6"
        />
      </g>
      <g className="arc-ring-inner">
        <circle
          cx="50" cy="50" r="27" fill="none" stroke="rgb(var(--arc-strong-rgb) / 0.7)" strokeWidth="2"
          pathLength="360" strokeDasharray="8 4"
        />
      </g>
      <polygon points="50,33 65,59 35,59" fill="none" stroke="rgb(var(--arc-strong-rgb))" strokeWidth="2.5" strokeLinejoin="round" />
      <circle className="arc-core" cx="50" cy="50" r="15" fill={`url(#${core})`} />
    </svg>
  );
}
