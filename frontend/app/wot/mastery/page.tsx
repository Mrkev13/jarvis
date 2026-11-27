"use client";

import { AreaBadge, ContentContainer, HudLabel, PageHeader, TextLink } from "@/components/ui";
import { MasteryTable } from "@/components/wot/MasteryTable";

/** MRK-152: M-ka všech tanků (Wargaming API, MRK-106) – vlastní stránka, z přehledu WoT odkazem. */
export default function WotMasteryPage() {
  return (
    <ContentContainer className="theme-wot">
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="M-ka všech tanků"
        subtitle="Nejvyšší odznak mistrovství u každého tanku z Wargaming API."
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <AreaBadge area="wot" />
            <TextLink href="/wot">← World of Tanks</TextLink>
          </span>
        }
      />
      <MasteryTable />
    </ContentContainer>
  );
}
