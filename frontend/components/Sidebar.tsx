"use client";

import { Icon } from "@/components/ui/Icon";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import NotificationsBell from "@/components/NotificationsBell";
import { JarvisCompanionToggle } from "@/components/jarvis/JarvisCompanionToggle";
import { QuickAddButton } from "@/components/quick-add/QuickAddButton";
import { SearchButton } from "@/components/search/SearchButton";
import { Drawer } from "@/components/ui/Drawer";
import { HudLabel, StatusPulse } from "@/components/ui/hud";
import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { MODULE_ACCESS } from "@/lib/moduleConfig";
import { navPagesFor } from "@/lib/navigation";
import { MAIN_CONTENT_ID } from "@/lib/shell";
import { cx } from "@/lib/ui";

interface SidebarProps {
  onNavigate?: (href: string) => void;
}

// Česká navigace (Roadmap 4A); seznam stránek sdílí s globálním vyhledáváním (lib/navigation.ts).
// Roadmap 6C: jen stránky dostupných modulů (desktop i mobilní menu používají tuto komponentu).
export const NAV_LINKS = navPagesFor(MODULE_ACCESS).map(({ href, label }) => ({ href, label }));

export function isActiveLink(href: string, pathname: string | null): boolean {
  return href === "/" ? pathname === "/" : Boolean(pathname?.startsWith(href));
}

export default function Sidebar({ onNavigate }: SidebarProps) {
  const pathname = usePathname();
  return (
    <nav aria-label="Hlavní navigace" className="space-y-0.5">
      {NAV_LINKS.map((link) => {
        const active = isActiveLink(link.href, pathname);
        return (
          <Link
            key={link.href}
            href={link.href}
            onClick={() => onNavigate?.(link.href)}
            aria-current={active ? "page" : undefined}
            className={cx(
              "relative block rounded-lg px-3 py-2.5 text-sm transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
              active ? "bg-surface-2 text-ink" : "text-ink-muted hover:bg-surface hover:text-ink",
            )}
          >
            {active ? (
              <span
                aria-hidden="true"
                className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-accent shadow-[0_0_10px_rgb(34_211_238/0.8)]"
              />
            ) : null}
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand({ as: Tag = "div" }: { as?: "div" | "p" }) {
  return (
    <Tag className="flex items-center gap-2.5">
      <span aria-hidden="true" className="grid h-8 w-8 place-items-center rounded-lg border border-accent/40 bg-accent/10 font-mono text-xs font-semibold text-accent-strong shadow-[0_0_16px_-6px_rgb(34_211_238/0.8)]">
        SH
      </span>
      <span className="leading-tight">
        <span className="block whitespace-nowrap text-base font-semibold text-ink">Standa Hub</span>
        <HudLabel className="flex items-center gap-1.5 text-[10px]">
          <StatusPulse tone="success" className="h-1.5 w-1.5" /> online
        </HudLabel>
      </span>
    </Tag>
  );
}

export function MobileHeader() {
  const [open, setOpen] = useState(false);
  // Po navigaci z menu se fokus nevrací na ☰, ale přesune do obsahu nové stránky.
  // navFrom = cesta, ze které uživatel v menu klikl (null = menu se zavřelo jinak).
  const [navFrom, setNavFrom] = useState<string | null>(null);
  const pathname = usePathname();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);

  useEffect(() => {
    queueMicrotask(() => setOpen(false));
    if (navFrom === null || pathname === navFrom) return;
    // Nová stránka se může vykreslit až po přechodu – <main> hledáme krátce opakovaně.
    let tries = 0;
    const t = window.setInterval(() => {
      const main = document.getElementById(MAIN_CONTENT_ID);
      tries += 1;
      if (main || tries > 20) {
        window.clearInterval(t);
        main?.focus({ preventScroll: true });
        setNavFrom(null);
      }
    }, 50);
    return () => window.clearInterval(t);
  }, [pathname, navFrom]);

  return (
    <>
      <header className="md:hidden sticky top-0 z-30 flex h-[var(--mobile-header-h)] items-center justify-between border-b border-line bg-app/90 px-4 backdrop-blur">
        <Brand />
        <div className="flex items-center gap-1">
          {/* Jen jeden zvonek v celé aplikaci (dřív se mobilní i desktopový dotazovaly zároveň). */}
          <QuickAddButton variant="icon" />
          <SearchButton variant="icon" />
          {isDesktop === false ? <NotificationsBell /> : null}
          <button
            type="button"
            aria-label="Otevřít menu"
            aria-expanded={open}
            aria-haspopup="dialog"
            onClick={() => setOpen(true)}
            className="grid h-10 w-10 place-items-center rounded-lg text-xl text-ink-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
          >
            <Icon name="menu" size="md" />
          </button>
        </div>
      </header>

      <Drawer
        open={open}
        onClose={() => setOpen(false)}
        title="Menu"
        width="sm"
        restoreFocus={navFrom === null}
        initialFocus={() => document.querySelector<HTMLElement>('[data-drawer-nav] a[aria-current="page"]')}
      >
        <div className="p-4" data-drawer-nav>
          <Sidebar
            onNavigate={(href) => {
              // klik na aktuální stránku = jen zavřít (fokus zpět na ☰)
              if (href !== pathname) setNavFrom(pathname);
              setOpen(false);
            }}
          />
        </div>
      </Drawer>
    </>
  );
}

export function DesktopSidebar() {
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  return (
    <aside data-desktop-sidebar className="hidden md:flex md:flex-col w-60 min-h-screen shrink-0 border-r border-line bg-app/80 px-4 py-5">
      <div className="mb-6 flex items-center justify-between gap-2 px-1">
        <Brand />
        {isDesktop === true ? <NotificationsBell /> : null}
      </div>
      <div className="mb-4 space-y-2">
        <SearchButton variant="field" />
        <QuickAddButton variant="field" />
      </div>
      <Sidebar />
      <div className="mt-auto hidden border-t border-line pt-3 lg:block">
        <JarvisCompanionToggle />
      </div>
    </aside>
  );
}
