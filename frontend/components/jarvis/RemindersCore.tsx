"use client";

import { useEffect, useState } from "react";
import { HudCore } from "@/components/jarvis/HudCore";
import { remindersCore } from "@/lib/hudModules";
import type { Reminder } from "@/lib/reminders";

/**
 * MRK-134: HUD odpočet do další připomínky (prstenec = posledních 12 h před ní). Čas se přepočítá jednou za minutu –
 * jediný časovač, žádné vteřinové tikání.
 */
export function RemindersCore({ items }: { items: Reminder[] }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    queueMicrotask(() => setNow(Date.now()));
    const t = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(t);
  }, []);
  if (now === null) return null;
  const model = remindersCore(items.map((r) => ({ title: r.title, status: String(r.status), state: String(r.state), due_at: r.due_at })), now);
  return <HudCore module="reminders" label="Jarvis · odpočet" {...model} />;
}
