"use client";

import { refreshModules } from "@/hooks/useModules";
import { useDomainEvents } from "@/hooks/useDomainEvents";
import { isModuleSettingsEvent, jarvisSignalFor } from "@/lib/domainEvents";
import { pulseJarvis } from "@/lib/jarvisSignals";

/**
 * MRK-19: první runtime konzumenti doménových událostí (nic nevykresluje):
 * - system.module.enabled / .disabled (i z jiné záložky / zařízení) → okamžitě znovu načíst stav modulů
 *   (bez reloadu stránky a bez pollingu – řeší známé omezení MRK-18),
 * - reset streamu → stav modulů načíst znovu (zmeškané události už nejsou k dispozici),
 * - čerstvé školní dokončení → krátká oslava Jarvise (mapovací tabulka v lib/domainEvents.ts).
 */
export function DomainEventsBridge() {
  useDomainEvents({
    onEvent: (e) => {
      if (isModuleSettingsEvent(e)) void refreshModules();
      const signal = jarvisSignalFor(e);
      if (signal) pulseJarvis(signal);
    },
    onReset: () => void refreshModules(),
  });
  return null;
}
