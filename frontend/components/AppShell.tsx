"use client";

import { usePathname } from "next/navigation";
import { DesktopSidebar, MobileHeader } from "@/components/Sidebar";
import { JarvisCompanion } from "@/components/jarvis/JarvisCompanion";
import { ModuleRouteGuard } from "@/components/modules/ModuleRouteGuard";
import { ModuleRuntimeLoader } from "@/components/modules/ModuleRuntimeLoader";
import { DomainEventsBridge } from "@/components/events/DomainEventsBridge";
import { PageTransition } from "@/components/motion/PageTransition";
import { SearchHighlighter } from "@/components/search/SearchHighlighter";
import { QuickAddProvider } from "@/components/quick-add/QuickAddProvider";
import { SearchProvider } from "@/components/search/SearchProvider";
import { companionLayout } from "@/lib/jarvisCompanion";
import { isBareRoute, MAIN_CONTENT_ID } from "@/lib/shell";

/**
 * Aplikační rám: navigace, zvonek, globální vyhledávání (Ctrl+K), Rychlé přidání (Ctrl+Shift+K), mřížka na pozadí.
 * Login (BARE_ROUTES) dostane jen pozadí – bez zvonku, vyhledávání, Rychlého přidání a bez dotazů na API,
 * které by bez session končily 401.
 */
export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  if (isBareRoute(pathname)) {
    return <div className="hud-grid min-h-screen">{children}</div>;
  }
  return (
    <SearchProvider>
      <QuickAddProvider>
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
            <div className="flex-1" data-jarvis-lane={companionLayout(pathname) === "ai" ? "ai" : "dock"}>
              <PageTransition>
                <ModuleRouteGuard>{children}</ModuleRouteGuard>
              </PageTransition>
            </div>
          </div>
          <SearchHighlighter />
          <ModuleRuntimeLoader />
          <DomainEventsBridge />
          <JarvisCompanion />
        </div>
      </QuickAddProvider>
    </SearchProvider>
  );
}
