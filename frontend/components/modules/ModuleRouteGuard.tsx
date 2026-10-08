"use client";

import { usePathname } from "next/navigation";
import { ContentContainer, EmptyState, ErrorState, LoadingState, PageHeader, TextLink } from "@/components/ui";
import { refreshModules, useModuleAccess } from "@/hooks/useModules";
import { routeDecision } from "@/lib/moduleRuntime";

/**
 * Roadmap 6C / MRK-18 A2: přímá adresa vypnutého modulu (záložka, starý odkaz z notifikace) neotevře jeho stránku.
 * Stav modulů je runtime (GET /modules). Dokud ho neznáme, stránka modulu se NEpřipojí (žádný obsah ani dotazy na
 * API vypnutého modulu) – jen načítání; bez spojení chyba s opakováním. Data navíc hlídá backend (404).
 * Není to oprávnění: auth řeší proxy.ts a backend nezávisle na flagu.
 */
export function ModuleRouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  const { access, snapshot } = useModuleAccess();
  const decision = routeDecision(snapshot, access, pathname);
  if (decision === "allow") return <>{children}</>;
  if (decision === "loading") {
    return (
      <ContentContainer>
        <div data-testid="module-loading">
          <LoadingState lines={3} label="Načítám moduly…" />
        </div>
      </ContentContainer>
    );
  }
  if (decision === "error") {
    return (
      <ContentContainer>
        <div data-testid="module-error">
          <ErrorState message="Nepodařilo se načíst stav modulů." onRetry={() => void refreshModules()} />
        </div>
      </ContentContainer>
    );
  }
  const label = access.moduleForPath(pathname)?.label ?? "Modul";
  return (
    <ContentContainer>
      <PageHeader title="Modul není dostupný" subtitle={`${label} je v této instalaci vypnutý.`} />
      <EmptyState action={<TextLink href="/">Zpět na Řídicí centrum →</TextLink>}>
        <span data-testid="module-unavailable">Tahle stránka teď není k dispozici. Data modulu zůstávají beze změny.</span>
      </EmptyState>
    </ContentContainer>
  );
}
