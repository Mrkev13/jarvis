/**
 * Frontendový manifest Návyků (MRK-21) – čistá data, žádný React (registr lib/modules.ts ho importuje, testy přes
 * node --test). Komponenty (stránka, widget) jsou v modules/habits/*.tsx a v modules/registry.tsx.
 */
import type { ModuleUi } from "../../lib/modules.ts";

export const HABITS_UI: ModuleUi = {
  nav: { href: "/habits", label: "Návyky", keywords: ["návyk", "návyky", "habits", "rutina", "rehab", "pitný režim"], order: 45 },
  searchParams: ["habit"],
  searchGroupOrder: 75,
  area: { bg: "bg-lime-500/10", border: "border-lime-400/30", text: "text-lime-200" },
  typeLabels: { habit: "Návyk" },
  todayActions: {
    habit: {
      complete: {
        button: "Splněno",
        ariaLabel: "Splnit návyk: {title}",
        success: "Návyk „{title}“ je splněný.",
        path: "/habits/{id}/entries?source=today",
        body: { state: "done" },
        primary: true,
      },
      skip: {
        button: "Přeskočit",
        ariaLabel: "Přeskočit návyk: {title}",
        success: "Návyk „{title}“ je pro dnešek přeskočený.",
        path: "/habits/{id}/entries?source=today",
        body: { state: "skipped" },
      },
    },
  },
  widgets: [
    // MRK-104: na hlavní obrazovce hned pod „Můj den" se Splnit / Přeskočit (data z GET /today, týden z /dashboard)
    { id: "habits_today", title: "Návyky", area: "habits", defaultVisible: true, defaultOrder: 25, defaultSize: "medium", allowedSizes: ["small", "medium", "large"], usesDashboardData: true, usesToday: true, modules: ["habits"] },
  ],
};
