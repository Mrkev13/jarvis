/**
 * MRK-131: zaměřovač v pravém horním rohu za obsahem (jen ≥ lg, app/hud.css `.hud-reticle`).
 * Dvě vrstvy se velmi pomalu protiběžně otáčejí – připomínka Jarvisova HUD, ne podnět k pozornosti.
 */
export function HudReticle() {
  return (
    <div className="hud-reticle" aria-hidden="true">
      <svg viewBox="0 0 400 400" fill="none" stroke="currentColor">
        <circle cx="200" cy="200" r="196" strokeWidth="1" />
        <circle cx="200" cy="200" r="150" strokeWidth="1" strokeDasharray="2 6" />
        <circle cx="200" cy="200" r="62" strokeWidth="1" />
        <g className="reticle-ticks">
          <circle cx="200" cy="200" r="178" strokeWidth="8" pathLength="360" strokeDasharray="0.6 2.4" />
          <circle cx="200" cy="200" r="178" strokeWidth="14" pathLength="360" strokeDasharray="1 29" />
        </g>
        <g className="reticle-arcs" strokeWidth="3">
          <circle cx="200" cy="200" r="118" pathLength="360" strokeDasharray="70 20 30 60 50 130" />
          <circle cx="200" cy="200" r="96" strokeWidth="1.5" pathLength="360" strokeDasharray="120 60" />
        </g>
        <path d="M200 0v120M200 280v120M0 200h120M280 200h120" strokeWidth="1" />
      </svg>
    </div>
  );
}
