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
  className,
}: {
  kind: GameAssetKind;
  /** Název z aplikace (tank, postava) nebo klíč měny (credits, gold, bonds, free_xp). */
  name: string;
  size?: GameImageSize;
  className?: string;
}) {
  const manifest = useGameAssetManifest();
  const src = manifest ? assetSrc(manifest, kind, name) : null;
  const [failed, setFailed] = useState<string | null>(null);
  const { width, height } = imageBox(kind, size);
  const alt = assetAlt(kind, name);
  const decorative = alt === "";
  const showImage = src !== null && failed !== src;

  const frame = cx(
    "relative inline-flex shrink-0 items-center justify-center overflow-hidden border border-line-subtle bg-surface-2",
    kind === "resource" ? "rounded-md" : kind === "character" ? "rounded-[var(--radius-control)]" : "rounded-[var(--radius-control)]",
    className,
  );
  const style = { width, height };

  if (showImage) {
    return (
      <span className={frame} style={style} data-game-image={kind} data-state="image">
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          unoptimized
          loading="lazy"
          onError={() => setFailed(src)}
          className={cx("h-full w-full", kind === "tank" ? "object-contain p-0.5" : "object-cover")}
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
            size === "xs" ? "text-[9px]" : size === "sm" ? "text-[11px]" : size === "md" ? "text-sm" : "text-base",
          )}
        >
          {monogram(kind, name)}
        </span>
      ) : null}
    </span>
  );
}
