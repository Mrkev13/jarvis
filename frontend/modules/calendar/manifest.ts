import type { ModuleUi } from '../../lib/modules.ts';

export const CALENDAR_UI: ModuleUi = {
  nav: { href: '/calendar', label: 'Kalendář', keywords: ['kalendář', 'calendar', 'událost', 'rozvrh'], order: 46 },
  searchParams: ['event'], searchGroupOrder: 85,
  typeLabels: { calendar_event: 'Událost' },
  area: { bg: 'bg-cyan-500/10', border: 'border-cyan-400/30', text: 'text-cyan-200' },
};
