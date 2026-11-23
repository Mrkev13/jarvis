"use client";

import { useEffect, useState } from "react";
import { ArcReactor } from "@/components/jarvis/ArcReactor";
import { BOOT_MS, BOOT_SESSION_KEY, bootGreeting, pragueHour, shouldBoot } from "@/lib/boot";
import { BOOT_REPLAY_EVENT, readHudPrefs, voiceGreeting } from "@/lib/hud";
import { playHudSound, whenActivated } from "@/lib/hudSound";
import { speakText } from "@/lib/speech";

/**
 * MRK-131: „start systému" – jednou za relaci se rozzáří arc reaktor, pošle dvě vlny a Jarvis pozdraví.
 * Za necelé 2 s se rozplyne. Jen dekorace: aria-hidden, pointer-events: none (stránka pod ním je hned klikací),
 * při omezeném pohybu se vůbec nezobrazí (app/hud.css + shouldBoot).
 */
export function BootSequence() {
  const [greeting, setGreeting] = useState<string | null>(null);

  useEffect(() => {
    let seen = false;
    try {
      seen = window.sessionStorage.getItem(BOOT_SESSION_KEY) === "1";
      window.sessionStorage.setItem(BOOT_SESSION_KEY, "1");
    } catch {
      seen = false;
    }
    const automated = Boolean(navigator.webdriver);
    const force = new URLSearchParams(window.location.search).get("boot") === "1";
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const greeting = bootGreeting(pragueHour());
    const cleanups: Array<() => void> = [];
    // MRK-133: hlasový pozdrav (výchozí vypnutý) – jednou za relaci i při omezeném pohybu (není to pohyb);
    // prohlížeč smí mluvit až po interakci, jinak se pozdrav odloží na první klik
    const prefs = readHudPrefs();
    if (prefs.voice && (force || (!seen && !automated))) {
      cleanups.push(whenActivated(() => void speakText(voiceGreeting(greeting), "cs-CZ")));
    }
    const run = shouldBoot({ seen, reducedMotion, automated, force });
    if (run) {
      queueMicrotask(() => setGreeting(greeting));
      if (prefs.sounds) cleanups.push(whenActivated(() => playHudSound("boot"), 4000));
      const t = window.setTimeout(() => setGreeting(null), BOOT_MS);
      cleanups.push(() => window.clearTimeout(t));
    }
    return () => cleanups.forEach((fn) => fn());
  }, []);

  // Codex review #102: „Přehrát start systému" z Nastavení – přehraje se na místě (klientská navigace na ?boot=1 by
  // efekt výše znovu nespustila, BootSequence zůstává namountovaný). Klik = interakce, zvuk smí hrát hned.
  useEffect(() => {
    let timer: number | undefined;
    const replay = () => {
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      window.clearTimeout(timer);
      setGreeting(null);
      requestAnimationFrame(() => setGreeting(bootGreeting(pragueHour())));
      if (readHudPrefs().sounds) playHudSound("boot");
      timer = window.setTimeout(() => setGreeting(null), BOOT_MS + 50);
    };
    window.addEventListener(BOOT_REPLAY_EVENT, replay);
    return () => {
      window.removeEventListener(BOOT_REPLAY_EVENT, replay);
      window.clearTimeout(timer);
    };
  }, []);

  if (!greeting) return null;
  return (
    <div className="boot-overlay" aria-hidden="true" data-boot-sequence="">
      <span className="boot-scan" />
      <div className="boot-stage">
        <div className="boot-reactor">
          <span className="boot-wave" />
          <span className="boot-wave boot-wave-2" />
          <ArcReactor size={112} />
        </div>
        <p className="boot-greeting">{greeting}</p>
        <p className="boot-status">
          <span className="status-pulse text-success" /> Všechny systémy online
        </p>
      </div>
    </div>
  );
}
