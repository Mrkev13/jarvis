"use client";

import { useEffect } from "react";
import { Button, Card, PageHeader } from "@/components/ui";
import { JarvisAvatar } from "@/components/jarvis/JarvisAvatar";
import { JARVIS_STATES, type JarvisState } from "@/lib/jarvisAvatar";
import { clearJarvisSource, publishJarvisSource, pulseJarvis, strollJarvis } from "@/lib/jarvisSignals";
import { MAIN_CONTENT_ID } from "@/lib/shell";

/** Ruční spouštění reakcí companiona (stejné signály, jaké posílají AI, briefing, Rychlé přidání a grindy). */
const MOODS: { state: JarvisState; label: string }[] = [
  { state: "idle", label: "Klid" },
  { state: "listening", label: "Poslouchá" },
  { state: "thinking", label: "Přemýšlí" },
  { state: "warning", label: "Čeká na potvrzení" },
];

export function JarvisCompanionPreview() {
  useEffect(() => () => clearJarvisSource("preview"), []);
  return (
    <main id={MAIN_CONTENT_ID} tabIndex={-1} className="mx-auto max-w-4xl space-y-6 p-4 focus:outline-none md:p-8">
      <PageHeader title="Jarvis companion – ukázka" subtitle="Vývojová stránka (MOTION_PREVIEW=1). Companion je vpravo dole." />
      <Card className="space-y-4">
        <p className="text-sm text-ink-muted">Trvající nálada (jako zdroj stránky):</p>
        <div className="flex flex-wrap gap-2">
          {MOODS.map((m) => (
            <Button key={m.state} variant="secondary" onClick={() => publishJarvisSource("preview", m.state)}>
              {m.label}
            </Button>
          ))}
        </div>
        <p className="text-sm text-ink-muted">Krátká reakce:</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => pulseJarvis("success")}>Úspěch</Button>
          <Button variant="secondary" onClick={() => pulseJarvis("error")}>Chyba</Button>
        </div>
        <p className="text-sm text-ink-muted">Pohyb (jinak sám zhruba každých 40–50 s v klidu):</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => strollJarvis()}>Projít se</Button>
        </div>
      </Card>
      <Card className="space-y-3">
        <p className="text-sm text-ink-muted">Statický avatar (MRK-10) zůstává pro karty a hlavičky:</p>
        <div className="flex flex-wrap gap-3">
          {JARVIS_STATES.map((s) => (
            <JarvisAvatar key={s} state={s} size="md" />
          ))}
        </div>
      </Card>
    </main>
  );
}
