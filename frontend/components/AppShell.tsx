"use client";

import { usePathname } from "next/navigation";
import { DesktopSidebar, MobileHeader } from "@/components/Sidebar";
import { PageTransition } from "@/components/motion/PageTransition";
import { SearchHighlighter } from "@/components/search/SearchHighlighter";
import { SearchProvider } from "@/components/search/SearchProvider";
import { isBareRoute, MAIN_CONTENT_ID } from "@/lib/shell";

/**
 * Aplikační rám: navigace, zvonek, globální vyhledávání (Ctrl+K), mřížka na pozadí. Login (BARE_ROUTES) dostane jen pozadí –
 * bez zvonku, bez vyhledávání a bez dotazů na API, které by bez session končily 401.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (isBareRoute(pathname)) {
    return <div className="hud-grid min-h-screen">{children}</div>;
  }
  return (
    <SearchProvider>
      <div className="flex min-h-screen">
        <a
          href={`#${MAIN_CONTENT_ID}`}
          className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-lg focus:bg-elevated focus:px-4 focus:py-2 focus:text-sm focus:text-ink focus:ring-2 focus:ring-accent/70"
        >
          Přeskočit na obsah
        </a>
        <DesktopSidebar />
        <div className="hud-grid flex min-w-0 flex-1 flex-col">
          <MobileHeader />
          <div className="flex-1">
            <PageTransition>{children}</PageTransition>
          </div>
        </div>
        <SearchHighlighter />
      </div>
    </SearchProvider>
  );
}
