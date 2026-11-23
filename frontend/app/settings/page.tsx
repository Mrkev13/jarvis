"use client";

import Link from "next/link";

import PushSettings from "@/components/PushSettings";
import { ModuleSettings } from "@/components/modules/ModuleSettings";
import { Card, CardHeader, ContentContainer, HudLabel, PageHeader } from "@/components/ui";
import { Icon } from "@/components/ui/Icon";

// MRK-18 A2: Nastavení (jádro) – sekce Moduly. MRK-122: Co se změnilo, Aktivita a Paměť nejsou v liště, vedou sem.
const HISTORY_PAGES = [
  { href: "/changes", label: "Co se změnilo", description: "Co je v Hubu nového od minulé návštěvy." },
  { href: "/activity", label: "Aktivita", description: "Úplná historie změn (audit)." },
  { href: "/memory", label: "Paměť", description: "Co si Jarvis pamatuje – úpravy a mazání." },
];

export default function SettingsPage() {
  return (
    <ContentContainer width="narrow">
      <PageHeader eyebrow={<HudLabel>Systém · nastavení</HudLabel>} title="Nastavení" subtitle="Moduly Standa Hubu – co se ukazuje v navigaci, vyhledávání, dashboardu a AI." />
      <div className="space-y-6">
        <Card data-settings-history="">
          <CardHeader title="Historie a paměť" description="Stránky, které nejsou v liště – najde je i Ctrl+K." />
          <ul className="mt-3 space-y-1">
            {HISTORY_PAGES.map((page) => (
              <li key={page.href}>
                <Link
                  href={page.href}
                  className="motion-nav-item flex min-h-11 items-center justify-between gap-3 rounded-lg px-3 py-2 hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
                >
                  <span className="min-w-0">
                    <span className="block text-sm text-ink">{page.label}</span>
                    <span className="block text-xs text-ink-muted">{page.description}</span>
                  </span>
                  <Icon name="chevron-right" size="sm" className="shrink-0 text-ink-faint" />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        {/* MRK-80: upozornění na telefon patří do Nastavení (dřív na stránce Připomínky) */}
        <div id="push" data-settings-push="" className="scroll-mt-24 space-y-3">
          <PushSettings />
          <Card data-settings-android-sound="">
            <CardHeader
              title="Zvuk připomínek na Androidu"
              description="Vibraci a trvalé oznámení nastaví Hub sám, zvuk určuje telefon."
            />
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-2">
              <li>Dlouze podrž oznámení od Standa Hubu (nebo Nastavení → Aplikace → Standa Hub / Chrome → Oznámení).</li>
              <li>Otevři kategorii, do které připomínky chodí, a zvol <b>Upozorňování</b> (ne Tiché).</li>
              <li>Zapni zvuk a vyber tón; případně „Přepsat režim Nerušit“.</li>
              <li>Hotovo nebo Odložit 10 min jde rovnou z oznámení – appku nemusíš otevírat.</li>
            </ol>
          </Card>
        </div>
        <ModuleSettings />
      </div>
    </ContentContainer>
  );
}
