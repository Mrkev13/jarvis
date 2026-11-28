/**
 * Frontendový manifest modulu Počítač (MRK-155, MRK-157) – čistá data. Stránka `/devices` (modules/computer/
 * ComputerPage.tsx), barva oblasti pro Aktivitu a „Co se změnilo“ (párování PC, příkazy).
 */
import type { ModuleUi } from "../../lib/modules.ts";

export const COMPUTER_UI: ModuleUi = {
  nav: { href: "/devices", label: "Počítač", keywords: ["počítač", "pc", "vypnout", "uspat", "zamknout", "spustit", "jarvis pro pc"], order: 56, group: "more" },
  area: { bg: "bg-slate-500/10", border: "border-slate-400/30", text: "text-slate-200" },
};
