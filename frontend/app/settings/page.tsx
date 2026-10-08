"use client";

import { ModuleSettings } from "@/components/modules/ModuleSettings";
import { ContentContainer, PageHeader } from "@/components/ui";

// MRK-18 A2: Nastavení (jádro). Zatím jen sekce Moduly; další volby se sem přidají jako vlastní karty.
export default function SettingsPage() {
  return (
    <ContentContainer width="narrow">
      <PageHeader title="Nastavení" subtitle="Moduly Standa Hubu – co se ukazuje v navigaci, vyhledávání, dashboardu a AI." />
      <ModuleSettings />
    </ContentContainer>
  );
}
