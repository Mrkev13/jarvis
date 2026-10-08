"use client";

import { useState } from "react";
import { Card, CardHeader, ErrorState, LoadingState } from "@/components/ui";
import { refreshModules, setModuleEnabled, useModules } from "@/hooks/useModules";
import { errorMessage } from "@/lib/api";
import { settingsModules, type RuntimeModule } from "@/lib/moduleRuntime";
import { cx } from "@/lib/ui";

/**
 * MRK-18 A2: Nastavení → Moduly. Přepínač mění jen uloženou volbu (PUT /modules/{id}); data modulu zůstávají.
 * Modul vynucený prostředím serveru je zamčený („Vynuceno konfigurací serveru") – přepínač nejde použít.
 */
export function ModuleSettings() {
  const snapshot = useModules();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const modules = settingsModules(snapshot.modules);

  async function toggle(m: RuntimeModule) {
    if (m.locked || busy) return;
    setBusy(m.id);
    setError(null);
    try {
      await setModuleEnabled(m.id, !m.enabled);
    } catch (err) {
      setError(errorMessage(err, "Změnu se nepodařilo uložit."));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card aria-labelledby="settings-modules-title" data-testid="module-settings">
      <CardHeader
        title={<span id="settings-modules-title">Moduly</span>}
        icon="folder"
        description="Vypnutý modul zmizí z navigace, vyhledávání, Dnes, dashboardu, Rychlého přidání i AI. Jeho data zůstávají."
      />
      {!snapshot.modules ? (
        snapshot.status === "error" ? (
          <ErrorState message="Stav modulů se nepodařilo načíst." onRetry={() => void refreshModules()} />
        ) : (
          <LoadingState lines={3} label="Načítám moduly…" />
        )
      ) : (
        <ul className="divide-y divide-line-subtle">
          {modules.map((m) => (
            <li key={m.id} className="flex items-center justify-between gap-4 py-3" data-module-row={m.id}>
              <div className="min-w-0">
                <p className="text-sm font-medium text-ink">{m.label}</p>
                {m.locked ? (
                  <p className="text-xs text-ink-muted" data-testid={`module-locked-${m.id}`}>
                    Vynuceno konfigurací serveru
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={m.enabled}
                aria-label={`${m.label}: ${m.enabled ? "zapnuto" : "vypnuto"}`}
                aria-describedby={m.locked ? `module-locked-${m.id}` : undefined}
                disabled={m.locked || busy !== null}
                data-testid={`module-toggle-${m.id}`}
                onClick={() => void toggle(m)}
                className={cx(
                  "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                  "disabled:cursor-not-allowed disabled:opacity-50",
                  m.enabled ? "border-accent/60 bg-accent/25" : "border-line bg-surface-2",
                )}
              >
                <span
                  aria-hidden="true"
                  className={cx(
                    "absolute h-4 w-4 rounded-full transition-transform",
                    m.enabled ? "translate-x-[22px] bg-accent-strong" : "translate-x-[3px] bg-ink-muted",
                  )}
                />
              </button>
            </li>
          ))}
        </ul>
      )}
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger" data-testid="module-settings-error">
          {error}
        </p>
      ) : null}
    </Card>
  );
}
