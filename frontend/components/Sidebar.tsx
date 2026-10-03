"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import NotificationsBell from "@/components/NotificationsBell";

interface SidebarProps {
  onNavigate?: () => void;
}

export default function Sidebar({ onNavigate }: SidebarProps) {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Dashboard" },
    { href: "/activity", label: "📜 Aktivita" },
    { href: "/wot", label: "World of Tanks" },
    { href: "/finance", label: "Finance" },
    { href: "/school", label: "School" },
    { href: "/work", label: "Work" },
    { href: "/mff", label: "Marvel Future Fight" },
    { href: "/goals", label: "Goals" },
    { href: "/planner", label: "Planner" },
    { href: "/reminders", label: "⏰ Připomínky" },
    { href: "/memory", label: "Memory" },
    { href: "/ai", label: "AI Assistant" },
  ];

  return (
    <nav className="space-y-2">
      {links.map((link) => {
        const isActive =
          link.href === "/"
            ? pathname === "/"
            : pathname?.startsWith(link.href);

        return (
          <Link
            key={link.href}
            onClick={onNavigate}
            className={`block p-3 rounded-lg transition-colors ${
              isActive
                ? "bg-zinc-800 text-white"
                : "hover:bg-zinc-800 text-zinc-400"
            }`}
            href={link.href}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function MobileHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    queueMicrotask(() => {
      setOpen(false);
    });
  }, [pathname]);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <header className="md:hidden flex items-center justify-between px-4 py-3 border-b border-zinc-800 bg-zinc-950 sticky top-0 z-30">
        <h1 className="text-lg font-bold">Standa Hub</h1>
        <div className="flex items-center gap-2">
          <NotificationsBell />
          <button
            type="button"
            aria-label="Otevřít menu"
            onClick={() => setOpen(true)}
            className="p-2 rounded-lg hover:bg-zinc-800 transition-colors text-2xl leading-none"
          >
            ☰
          </button>
        </div>
      </header>

      {open && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <aside
            className="absolute right-0 top-0 h-full w-72 max-w-[85%] bg-zinc-950 border-l border-zinc-800 p-6 shadow-2xl animate-in slide-in-from-right"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-8">
              <h2 className="text-2xl font-bold">Standa Hub</h2>
              <button
                type="button"
                aria-label="Zavřít menu"
                onClick={() => setOpen(false)}
                className="p-2 rounded-lg hover:bg-zinc-800 transition-colors text-xl leading-none"
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
  return (
    <aside className="hidden md:block w-64 min-h-screen bg-zinc-950 border-r border-zinc-800 p-6 shrink-0">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-2xl font-bold">Standa Hub</h1>
        <NotificationsBell />
      </div>
      <Sidebar />
    </aside>
  );
}
