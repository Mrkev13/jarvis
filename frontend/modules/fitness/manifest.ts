import type { ModuleUi } from '../../lib/modules.ts';
export const FITNESS_UI: ModuleUi = {
  nav: { href: '/fitness', label: 'Fitness & Rehab', keywords: ['fitness', 'rehab', 'cvičení', 'trénink', 'rehabilitace'], order: 47 },
  searchParams: ['exercise', 'workout', 'rehab_exercise', 'rehab_session'], searchGroupOrder: 90,
  typeLabels: { fitness_exercise: 'Cvik', fitness_workout: 'Trénink', fitness_rehab_exercise: 'Rehab cvik', fitness_rehab_session: 'Rehab záznam' },
  area: { bg: 'bg-emerald-500/10', border: 'border-emerald-400/30', text: 'text-emerald-200' },
};
