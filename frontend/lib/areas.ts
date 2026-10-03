/**
 * Oblasti (škola, práce, finance…) – identita, ne stav (Roadmap 4B: jedno místo místo kopií).
 * Celé názvy tříd zde doslova, aby je Tailwind našel. Testy: areas.test.mjs.
 */
export const AREA_STYLES: Record<string, { bg: string; border: string; text: string; label: string }> = {
  school:   { bg: "bg-indigo-500/10",    border: "border-indigo-400/30",    text: "text-indigo-200",    label: "Škola" },
  work:     { bg: "bg-emerald-500/10",  border: "border-emerald-400/30",  text: "text-emerald-200",  label: "Práce" },
  finance:  { bg: "bg-amber-500/10",    border: "border-amber-400/30",    text: "text-amber-200",    label: "Finance" },
  wot:      { bg: "bg-orange-500/10",   border: "border-orange-400/30",   text: "text-orange-200",   label: "World of Tanks" },
  mff:      { bg: "bg-purple-500/10",   border: "border-purple-400/30",   text: "text-purple-200",   label: "Marvel FF" },
  personal: { bg: "bg-pink-500/10",     border: "border-pink-400/30",     text: "text-pink-200",     label: "Osobní" },
  fitness:  { bg: "bg-green-500/10",    border: "border-green-400/30",    text: "text-green-200",    label: "Fitness" },
  hobby:    { bg: "bg-rose-500/10",     border: "border-rose-400/30",     text: "text-rose-200",     label: "Hobby" },
  travel:   { bg: "bg-teal-500/10",     border: "border-teal-400/30",     text: "text-teal-200",     label: "Cestování" },
  general:  { bg: "bg-zinc-500/10",     border: "border-zinc-400/30",     text: "text-zinc-200",     label: "Obecné" },
  reminders: { bg: "bg-sky-500/10",     border: "border-sky-400/30",      text: "text-sky-200",      label: "Připomínky" },
  briefing: { bg: "bg-cyan-500/10",     border: "border-cyan-400/30",     text: "text-cyan-200",     label: "Přehled" },
  review:   { bg: "bg-violet-500/10",   border: "border-violet-400/30",   text: "text-violet-200",   label: "Týdenní přehled" },
  // oblasti auditu (Aktivita)
  goals:    { bg: "bg-sky-500/10",      border: "border-sky-400/30",      text: "text-sky-200",      label: "Cíle" },
  memory:   { bg: "bg-zinc-500/10",     border: "border-zinc-400/30",     text: "text-zinc-200",     label: "Paměť" },
  ai:       { bg: "bg-violet-500/10",   border: "border-violet-400/30",   text: "text-violet-200",   label: "AI" },
  system:   { bg: "bg-zinc-500/10",     border: "border-zinc-400/30",     text: "text-zinc-200",     label: "Systém" },
};

export function areaMeta(area: string | undefined | null) {
  return (
    AREA_STYLES[String(area ?? "").toLowerCase()] ?? {
      bg: "bg-zinc-500/10",
      border: "border-zinc-400/30",
      text: "text-zinc-200",
      label: String(area ?? "Obecné"),
    }
  );
}

