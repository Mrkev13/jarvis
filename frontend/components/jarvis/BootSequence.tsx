"use client";

import { useEffect, useState } from "react";
import { ArcReactor } from "@/components/jarvis/ArcReactor";
import { BOOT_MS, BOOT_SESSION_KEY, bootGreeting, pragueHour, shouldBoot } from "@/lib/boot";

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
    const run = shouldBoot({
      seen,
      reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      automated: Boolean(navigator.webdriver),
      force: new URLSearchParams(window.location.search).get("boot") === "1",
    });
    if (!run) return;
    queueMicrotask(() => setGreeting(bootGreeting(pragueHour())));
    const t = window.setTimeout(() => setGreeting(null), BOOT_MS);
    return () => window.clearTimeout(t);
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
