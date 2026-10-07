"use client";

import { usePathname } from "next/navigation";
import { ContentContainer, EmptyState, PageHeader, TextLink } from "@/components/ui";
import { MODULE_ACCESS } from "@/lib/moduleConfig";

/**
 * Roadmap 6C: přímá adresa vypnutého modulu (záložka, starý odkaz z notifikace) neotevře jeho stránku.
 * Stránka se vůbec nepřipojí (žádné dotazy na API) – místo ní čistý stav „Modul není dostupný" s cestou
 * na Řídicí centrum. Nespoléhá na skrytou navigaci; data navíc hlídá backend (404 pro API vypnutého modulu).
 * Není to oprávnění: auth řeší proxy.ts a backend nezávisle na flagu.
 */
export function ModuleRouteGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/";
  if (MODULE_ACCESS.allowsPath(pathname)) return <>{children}</>;
  const label = MODULE_ACCESS.moduleForPath(pathname)?.label ?? "Modul";
  return (
    <ContentContainer>
      <PageHeader title="Modul není dostupný" subtitle={`${label} je v této instalaci vypnutý.`} />
      <EmptyState action={<TextLink href="/">Zpět na Řídicí centrum →</TextLink>}>
        <span data-testid="module-unavailable">Tahle stránka teď není k dispozici. Data modulu zůstávají beze změny.</span>
      </EmptyState>
    </ContentContainer>
  );
}
