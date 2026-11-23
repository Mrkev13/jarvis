import { staggerStyle } from "@/lib/motion";
import { isIconName, type IconName } from "@/lib/icons";
import { CARD_TONE, cx, type Tone } from "@/lib/ui";
import { IconTile } from "./Icon";

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
  as?: "section" | "div" | "article" | "li" | "aside";
  className?: string;
} & Omit<React.HTMLAttributes<HTMLElement>, "className" | "children">;

/**
 * Základní plocha. MRK-131: karta je „skleněný panel" Jarvisova HUD – světelná horní hrana a zaměřovací rohy při
 * najetí / fokusu (app/hud.css `.hud-panel`); neutrální tóny jsou na širších displejích průsvitné (`.hud-glass`).
 * Vnořené plochy (inset) zůstávají čisté.
 */
const GLASS_TONES: Tone[] = ["neutral", "accent", "ai", "info"];

/**
 * Codex review #99: průsvitnost skla musí dát utilita (bg-surface/80 od md), jinak výchozí `bg-surface` z CARD_TONE
 * (vrstva utilities) přebije barvu z `.hud-glass` a rozmazání se počítá pod neprůhlednou plochou.
 */
function toneClass(tone: Tone): string {
  return GLASS_TONES.includes(tone) ? cx(CARD_TONE[tone].replace("bg-surface", "bg-surface md:bg-surface/80"), "hud-glass") : CARD_TONE[tone];
}

export function Card({ children, tone = "neutral", inset, flush, index, as: Tag = "section", className, style, ...rest }: CardProps) {
  return (
    <Tag
      {...rest}
      style={index === undefined ? style : { ...staggerStyle(index), ...style }}
      className={cx(
        index === undefined ? null : "motion-card",
        "border",
        inset
          ? "rounded-[var(--radius-control)] border-line-subtle bg-surface-2"
          : cx("hud-panel rounded-card shadow-card", toneClass(tone)),
        flush ? null : inset ? "p-3" : "p-4 md:p-5",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/**
 * Hlavička karty: ikona, titulek (h2/h3), akce vpravo. `icon` = název ze sady ikon (MRK-15, doporučeno →
 * jednotný „duotone" rámeček) nebo vlastní uzel (zpětná kompatibilita).
 */
export function CardHeader({
  title,
  icon,
  actions,
  description,
  as: Heading = "h2",
}: {
  title: React.ReactNode;
  icon?: IconName | React.ReactNode;
  actions?: React.ReactNode;
  description?: React.ReactNode;
  as?: "h2" | "h3";
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-3 gap-y-2">
      <div className="min-w-0">
        <Heading className="flex items-center gap-2 font-display text-base md:text-lg font-semibold tracking-wide text-ink">
          {isIconName(icon) ? (
            <IconTile name={icon} />
          ) : icon ? (
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
