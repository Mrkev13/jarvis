"use client";

import { useEffect, useState } from "react";
import { Button, Card, CardHeader } from "@/components/ui";
import { fieldClass } from "@/components/ui/forms";
import { BOOT_REPLAY_EVENT, HUD_PREFS_EVENT, readHudPrefs, writeHudPrefs, type HudPrefs } from "@/lib/hud";
import { pragueHour } from "@/lib/boot";
import { playHudSound } from "@/lib/hudSound";
import { PIPER_VOICE, pickVoice, sayGreeting, usesStudioVoice, voiceOptions, type VoiceLike } from "@/lib/hudVoice";
import { isSpeechSynthesisSupported } from "@/lib/speech";
import { cx } from "@/lib/ui";

/**
 * MRK-133: Nastavení → Jarvis HUD. Zvuky systému a hlasový pozdrav (obojí výchozí vypnuté, jen v tomto
 * prohlížeči – localStorage), vyzkoušení a ruční přehrání startu systému.
 */
export function HudSettings() {
  const [prefs, setPrefs] = useState<HudPrefs | null>(null);
  // MRK-136: hlasy prohlížeče (načítají se asynchronně – voiceschanged)
  const [voices, setVoices] = useState<VoiceLike[]>([]);

  useEffect(() => {
    const sync = () => setPrefs(readHudPrefs());
    queueMicrotask(sync);
    window.addEventListener(HUD_PREFS_EVENT, sync);
    const synth = isSpeechSynthesisSupported() ? window.speechSynthesis : null;
    const loadVoices = () => setVoices((synth?.getVoices?.() ?? []).map((v) => ({ name: v.name, lang: v.lang, voiceURI: v.voiceURI, localService: v.localService })));
    queueMicrotask(loadVoices);
    synth?.addEventListener?.("voiceschanged", loadVoices);
    return () => {
      window.removeEventListener(HUD_PREFS_EVENT, sync);
      synth?.removeEventListener?.("voiceschanged", loadVoices);
    };
  }, []);

  const lang = prefs?.voiceLang ?? "cs";
  const options = voiceOptions(voices, lang);
  const studio = prefs ? usesStudioVoice(prefs) : true;
  const current = prefs && !studio ? pickVoice(voices, prefs) : null;

  const update = (patch: Partial<HudPrefs>) => {
    const next = { ...(prefs ?? readHudPrefs()), ...patch };
    writeHudPrefs(next);
    setPrefs(next);
  };

  return (
    <Card data-settings-hud="">
      <CardHeader
        title="Jarvis HUD"
        description="Zvuky a hlas Jarvise. Platí jen v tomhle prohlížeči; při omezeném pohybu se animace vynechají."
      />
      <div className="mt-2 space-y-1">
        <Switch
          label="Zvuky systému"
          hint="Tiché tóny při startu, dokončení úkolu a splněné misi."
          checked={prefs?.sounds ?? false}
          disabled={!prefs}
          onChange={(v) => update({ sounds: v })}
        />
        <Switch
          label="Hlasový pozdrav"
          // až po hydrataci (prefs) – server o předčítání prohlížeče neví
          hint={prefs && !isSpeechSynthesisSupported() ? "Tenhle prohlížeč neumí předčítat." : "Jarvis tě při prvním otevření pozdraví nahlas."}
          checked={prefs?.voice ?? false}
          disabled={!prefs}
          onChange={(v) => update({ voice: v })}
        />
      </div>
      {/* MRK-136: jazyk a hlas pozdravu – nejlepší (přirozené / online) hlasy nahoře */}
      <div className="mt-3 grid gap-3 px-3 sm:grid-cols-2">
        <label className="block text-sm text-ink-2">
          Jazyk pozdravu
          <select
            aria-label="Jazyk pozdravu"
            className={cx(fieldClass, "mt-1")}
            value={lang}
            disabled={!prefs}
            onChange={(e) => update({ voiceLang: e.target.value === "en" ? "en" : "cs", voiceURI: null })}
          >
            <option value="cs">Čeština</option>
            <option value="en">English (britský – jako ve filmu)</option>
          </select>
        </label>
        <label className="block text-sm text-ink-2">
          Hlas
          <select
            aria-label="Hlas Jarvise"
            className={cx(fieldClass, "mt-1")}
            value={studio ? PIPER_VOICE : current?.voiceURI ?? PIPER_VOICE}
            disabled={!prefs}
            onChange={(e) => update({ voiceURI: e.target.value === PIPER_VOICE ? null : e.target.value })}
          >
            {/* MRK-136: studiový hlas (Piper, předgenerované pozdravy) je výchozí a zní nejlépe */}
            <option value={PIPER_VOICE}>Jarvis – studiový hlas (doporučený)</option>
            {options.map((v, i) => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name}{i === 0 ? " – nejlepší v prohlížeči" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="mt-2 px-3 text-xs text-ink-muted">
        Prohlížeč smí mluvit až po interakci: po zadání PINu pozdraví hned, jinak po prvním kliknutí. Studiový hlas je
        předem nahraný neuronovým hlasem Piper (britský mužský / český); hlasy prohlížeče jsou záloha.
      </p>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={() => playHudSound("mission", true)}>
          Zkusit zvuk
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void sayGreeting(prefs ?? readHudPrefs(), pragueHour())}
        >
          Zkusit hlas
        </Button>
        <Button size="sm" variant="secondary" onClick={() => window.dispatchEvent(new Event(BOOT_REPLAY_EVENT))}>
          Přehrát start systému
        </Button>
      </div>
    </Card>
  );
}

function Switch({ label, hint, checked, disabled, onChange }: { label: string; hint: string; checked: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="flex min-h-12 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left hover:bg-surface focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 disabled:opacity-60"
    >
      <span className="min-w-0">
        <span className="block text-sm text-ink">{label}</span>
        <span className="block text-xs text-ink-muted">{hint}</span>
      </span>
      <span aria-hidden="true" className={cx("relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors", checked ? "border-accent/60 bg-accent/25" : "border-line bg-surface-2")}>
        <span className={cx("absolute h-3.5 w-3.5 rounded-full transition-transform", checked ? "translate-x-[18px] bg-accent-strong shadow-[0_0_8px_rgb(60_200_245/0.8)]" : "translate-x-[2px] bg-ink-muted")} />
      </span>
    </button>
  );
}
