"use client";

import Image from "next/image";
import { useState } from "react";
import { useGameAssetManifest } from "@/hooks/useGameAssets";
import { assetAlt, assetSrc, imageBox, monogram, type GameAssetKind, type GameImageSize } from "@/lib/gameAssets";
import { cx } from "@/lib/ui";

/**
 * Herní obrázek (Game Enrichment A): tank, portrét postavy MFF nebo ikona měny WoT. Pevný rámeček podle
 * velikostního tokenu (žádný layout shift), líné načítání, lokální soubor z /game-assets (same-origin).
 * Chybějící asset, chyba načtení nebo výpadek → čitelný monogram ve stejném rámečku, nikdy rozbitý obrázek.
 * Text (název, částka) zůstává vždy vedle obrázku – obrázek jen pomáhá rozpoznat.
 */
export function GameImage({
  kind,
  name,
  size = "sm",
  mobileSize,
  className,
}: {
  kind: GameAssetKind;
  /** Název z aplikace (tank, postava) nebo klíč měny (credits, gold, bonds, free_xp). */
  name: string;
  size?: GameImageSize;
  /** Menší rámeček pod breakpointem md (mobil) – text vedle obrázku dostane víc místa. */
  mobileSize?: GameImageSize;
  className?: string;
}) {
  const manifest = useGameAssetManifest();
  const src = manifest ? assetSrc(manifest, kind, name) : null;
  const [failed, setFailed] = useState<string | null>(null);
  const { width, height } = imageBox(kind, size);
  const small = imageBox(kind, mobileSize ?? size);
  const alt = assetAlt(kind, name);
  const decorative = alt === "";
  const showImage = src !== null && failed !== src;

  const frame = cx(
    "relative inline-flex shrink-0 items-center justify-center overflow-hidden border border-line-subtle bg-surface-2",
    // rozměry z proměnných: pevný rámeček na každé šířce (žádný layout shift), menší na mobilu
    "h-[var(--gi-h-sm)] w-[var(--gi-w-sm)] md:h-[var(--gi-h)] md:w-[var(--gi-w)]",
    kind === "resource" ? "rounded-md" : kind === "character" ? "rounded-[var(--radius-control)]" : "rounded-[var(--radius-control)]",
    className,
  );
  const style = {
    "--gi-w": `${width}px`,
    "--gi-h": `${height}px`,
    "--gi-w-sm": `${small.width}px`,
    "--gi-h-sm": `${small.height}px`,
  } as React.CSSProperties;

  if (showImage) {
    // Rendery tanků z Tankopedie jsou tmavé a průhledné → na tmavé ploše splývají. Jen prezentace (zdroj beze změny):
    // jemné světlejší pozadí uprostřed rámečku + mírné zjasnění obrázku.
    const tankBackdrop =
      kind === "tank" ? "bg-[radial-gradient(ellipse_at_center,color-mix(in_srgb,var(--color-ink-2)_24%,transparent),transparent_72%)]" : null;
    return (
      <span className={cx(frame, tankBackdrop)} style={style} data-game-image={kind} data-state="image">
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          unoptimized
          loading="lazy"
          onError={() => setFailed(src)}
          className={cx(
            "h-full w-full",
            kind === "tank" ? "object-contain p-0.5 brightness-[1.2] contrast-[1.05]" : kind === "resource" ? "object-contain p-[3px]" : "object-cover",
          )}
        />
      </span>
    );
  }
  // načítání manifestu i záložní stav: stejný rámeček; monogram až když je jasné, že obrázek nebude
  const fallback = manifest !== null;
  return (
    <span
      className={frame}
      style={style}
      data-game-image={kind}
      data-state={fallback ? "fallback" : "loading"}
      role={decorative || !fallback ? undefined : "img"}
      aria-label={decorative || !fallback ? undefined : alt}
      aria-hidden={decorative || !fallback ? true : undefined}
    >
      {fallback ? (
        <span
          className={cx(
            "select-none font-mono font-semibold uppercase tracking-wide text-ink-muted",
            (mobileSize ?? size) === "xs" ? "text-[9px]" : (mobileSize ?? size) === "sm" ? "text-[11px]" : "text-sm",
            size === "md" ? "md:text-sm" : size === "lg" ? "md:text-base" : null,
          )}
        >
          {monogram(kind, name)}
        </span>
      ) : null}
    </span>
  );
}
