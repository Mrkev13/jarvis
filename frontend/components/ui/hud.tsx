import { cx, TEXT_TONE, type Tone } from "@/lib/ui";

/**
 * Jarvis/HUD akcenty (Roadmap 4A). Volitelné a dekorativní – nikdy nenesou informaci samy o sobě
 * (text vedle nich musí stačit) a nepřekrývají obsah. Používej střídmě: 1–2 zvýrazněné panely na obrazovku.
 */

/** Rohové značky kolem panelu. `violet` pro AI / odhady. */
export function HudFrame({
  children,
  variant = "cyan",
  className,
}: {
  children: React.ReactNode;
  variant?: "cyan" | "violet";
  className?: string;
}) {
  return <div className={cx("hud-frame rounded-card", variant === "violet" && "hud-frame-violet", className)}>{children}</div>;
}

/** Technický mikro-štítek (monospace, velká písmena) – popisky metrik, metadata. */
export function HudLabel({
  children,
  as: Tag = "span",
  tone,
  className,
}: {
  children: React.ReactNode;
  as?: "span" | "div" | "p";
  tone?: Tone;
  className?: string;
}) {
  return (
    <Tag className={cx("font-mono text-[11px] uppercase tracking-[0.14em]", tone ? TEXT_TONE[tone] : "text-ink-muted", className)}>
      {children}
    </Tag>
  );
}

/** Tenká světelná linka – horní hrana aktivního panelu nebo oddělovač. */
export function AccentLine({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("accent-line", className)} />;
}

/** Stavová tečka; `live` = jemný pulz (při omezeném pohybu statický prstenec). Doplňuj textem. */
export function StatusPulse({ tone = "accent", live, className }: { tone?: Tone; live?: boolean; className?: string }) {
  return <span aria-hidden="true" className={cx("status-pulse", live && "status-pulse-live", TEXT_TONE[tone], className)} />;
}
