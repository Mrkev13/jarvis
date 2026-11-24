/* eslint-disable @next/next/no-img-element -- obrázky z CDN Blizzardu (render.worldofwarcraft.com), bez Next optimalizace */
import { cx } from "@/lib/ui";
import { classRgb, safeRenderUrl, targetProgress, type WowCharacter } from "./lib";

/**
 * MRK-139: prvky hrdinské karty WoW – prstenec levelu (postup k cílovému levelu) s avatarem uvnitř a „flotila"
 * (řada avatarů nahoře). Obrázky jen z oficiálního render hostu (safeRenderUrl), bez referreru; bez obrázku iniciála.
 */
export function LevelRing({ c, size = 64 }: { c: WowCharacter; size?: number }) {
  const pct = targetProgress(c);
  const r = 28;
  const len = 2 * Math.PI * r;
  const avatar = safeRenderUrl(c.avatar_url);
  return (
    <span className="wow-ring relative inline-grid shrink-0 place-items-center" style={{ width: size, height: size }} aria-hidden="true">
      <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" strokeWidth="4" className="wow-ring-track" />
        {pct != null ? (
          <circle cx="32" cy="32" r={r} fill="none" strokeWidth="4" strokeLinecap="round" className={cx("wow-ring-fill", c.at_target && "wow-ring-done")}
            strokeDasharray={`${(len * pct) / 100} ${len}`} />
        ) : null}
      </svg>
      <span className="wow-ring-face grid place-items-center overflow-hidden rounded-full" style={{ width: size - 14, height: size - 14 }}>
        {avatar ? (
          <img src={avatar} alt="" referrerPolicy="no-referrer" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <span className="font-display text-lg font-bold text-ink-2">{c.name.slice(0, 1)}</span>
        )}
      </span>
      <span className="wow-ring-level font-display">{c.level ?? "?"}</span>
    </span>
  );
}

/** Flotila: řada avatarů s levelem – klik skočí na kartu postavy. */
export function Fleet({ characters }: { characters: WowCharacter[] }) {
  if (characters.length < 2) return null;
  return (
    <nav aria-label="Flotila altů" data-wow-fleet="" className="wow-fleet -mx-1 flex gap-3 overflow-x-auto px-1 pb-1">
      {characters.map((c) => (
        <a
          key={c.id}
          href={`/wow?wowchar=${c.id}`}
          onClick={(e) => {
            // karta nemá id – najde se podle cíle vyhledávání a plynule se k ní sjede
            const card = document.querySelector<HTMLElement>(`[data-search-target="wowchar-${c.id}"]`);
            if (!card) return;
            e.preventDefault();
            card.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
          }}
          style={{ ["--class-rgb" as string]: classRgb(c.class_name) ?? "155 227 255" } as React.CSSProperties}
          className="flex shrink-0 flex-col items-center gap-1 rounded-lg p-1 text-xs text-ink-2 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70">
          <LevelRing c={c} size={52} />
          <span className="max-w-[6rem] truncate">{c.name}</span>
        </a>
      ))}
    </nav>
  );
}
