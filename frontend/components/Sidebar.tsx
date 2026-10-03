"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import NotificationsBell from "@/components/NotificationsBell";
import { HudLabel, StatusPulse } from "@/components/ui/hud";
import { DESKTOP_QUERY, useMediaQuery } from "@/hooks/useMediaQuery";
import { lockScroll } from "@/lib/dialog";
import { cx } from "@/lib/ui";

interface SidebarProps {
  onNavigate?: () => void;
}

// Česká navigace (Roadmap 4A); vlastní jména her zůstávají.
export const NAV_LINKS = [
  { href: "/", label: "Řídicí centrum" },
  { href: "/review", label: "Týdenní přehled" },
  { href: "/planner", label: "Plánovač" },
  { href: "/reminders", label: "Připomínky" },
  { href: "/goals", label: "Cíle" },
  { href: "/school", label: "Škola" },
  { href: "/work", label: "Práce" },
  { href: "/finance", label: "Finance" },
  { href: "/wot", label: "World of Tanks" },
  { href: "/mff", label: "Marvel Future Fight" },
  { href: "/activity", label: "Aktivita" },
  { href: "/memory", label: "Paměť" },
  { href: "/ai", label: "AI asistent" },
];

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
            onClick={onNavigate}
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
        <span className="block text-base font-semibold text-ink">Standa Hub</span>
        <HudLabel className="flex items-center gap-1.5 text-[10px]">
          <StatusPulse tone="success" className="h-1.5 w-1.5" /> online
        </HudLabel>
      </span>
    </Tag>
  );
}

export function MobileHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);

  useEffect(() => {
    queueMicrotask(() => setOpen(false));
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    return lockScroll();
  }, [open]);

  return (
    <>
      <header className="md:hidden sticky top-0 z-30 flex items-center justify-between border-b border-line bg-app/90 px-4 py-2.5 backdrop-blur">
        <Brand />
        <div className="flex items-center gap-1">
          {/* Jen jeden zvonek v celé aplikaci (dřív se mobilní i desktopový dotazovaly zároveň). */}
          {isDesktop === false ? <NotificationsBell /> : null}
          <button
            type="button"
            aria-label="Otevřít menu"
            aria-expanded={open}
            onClick={() => setOpen(true)}
            className="grid h-10 w-10 place-items-center rounded-lg text-xl text-ink-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
          >
            ☰
          </button>
        </div>
      </header>

      {open && (
        <div className="md:hidden fixed inset-0 z-40 bg-black/70 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <aside
            aria-label="Menu"
            className="absolute right-0 top-0 h-full w-72 max-w-[85%] overflow-y-auto border-l border-line bg-app p-5 shadow-[var(--shadow-elevated)]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-6 flex items-center justify-between">
              <Brand />
              <button
                type="button"
                aria-label="Zavřít menu"
                onClick={() => setOpen(false)}
                className="grid h-10 w-10 place-items-center rounded-lg text-xl text-ink-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
              >
                ×
              </button>
            </div>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
    </>
  );
}

export function DesktopSidebar() {
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  return (
    <aside className="hidden md:flex md:flex-col w-60 min-h-screen shrink-0 border-r border-line bg-app/80 px-4 py-5">
      <div className="mb-6 flex items-center justify-between gap-2 px-1">
        <Brand />
        {isDesktop === true ? <NotificationsBell /> : null}
      </div>
      <Sidebar />
    </aside>
  );
}
