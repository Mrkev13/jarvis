/**
 * Registr React částí modulů z balíčků modules/<id>/ (MRK-21) – jeden řádek na modul. Čistá data modulů
 * (navigace, akce Dnes, definice widgetů…) jsou v lib/modules.ts (`MODULE_UI`); tady jen komponenty pod stejnými id.
 */
import type { WidgetProps } from "@/components/dashboard/widgets";
import { HabitsTodayWidget } from "./habits/HabitsTodayWidget";

export const MODULE_WIDGET_COMPONENTS: Record<string, (props: WidgetProps) => React.ReactNode> = {
  habits_today: HabitsTodayWidget,
};
