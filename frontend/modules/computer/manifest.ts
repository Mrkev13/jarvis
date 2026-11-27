/**
 * Frontendový manifest modulu Počítač (MRK-155) – čistá data. Zatím jen barva oblasti pro Aktivitu a „Co se
 * změnilo“ (párování PC, příkazy); stránka Počítač a navigace přijdou s MRK-157.
 */
import type { ModuleUi } from "../../lib/modules.ts";

export const COMPUTER_UI: ModuleUi = {
  area: { bg: "bg-slate-500/10", border: "border-slate-400/30", text: "text-slate-200" },
};
