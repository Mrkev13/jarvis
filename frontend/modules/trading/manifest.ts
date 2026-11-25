/**
 * Frontendový manifest Tradingu (MRK-141) – čistá data, žádný React. Stránka je modules/trading/TradingPage.tsx,
 * data z backendu `GET /trading` (read-only API stacku standa-trading). Žádné vyhledávání ani AI (finance, MRK-60).
 */
import type { ModuleUi } from "../../lib/modules.ts";

export const TRADING_UI: ModuleUi = {
  nav: { href: "/trading", label: "Trading", keywords: ["trading", "algo", "paper", "akcie", "strategie", "spy", "burza"], order: 54, group: "more" },
  area: { bg: "bg-emerald-500/10", border: "border-emerald-400/30", text: "text-emerald-200" },
};
