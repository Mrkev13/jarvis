"use client";

import { useEffect, useState } from "react";
import { ArcReactor } from "@/components/jarvis/ArcReactor";
import { MISSION_EVENT, type Mission } from "@/lib/hud";
import { playHudSound } from "@/lib/hudSound";

const MISSION_MS = 2000;

/**
 * MRK-133: „Mise splněna" – krátká oslava přes celou obrazovku (reaktor se rozzáří, vlna, nápis) po čerstvé
 * doménové události (lib/hud.ts missionFor). Jen dekorace: aria-hidden, pointer-events: none; informaci nese
 * stávající hláška stránky. Při omezeném pohybu se neukáže; během jedné oslavy se další ignorují.
 */
export function MissionComplete() {
  const [mission, setMission] = useState<Mission | null>(null);

  useEffect(() => {
    let timer: number | undefined;
    let showing = false;
    const onMission = (e: Event) => {
      const m = (e as CustomEvent<Mission>).detail;
      if (!m || showing) return;
      playHudSound("mission");
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      showing = true;
      setMission(m);
      timer = window.setTimeout(() => {
        showing = false;
        setMission(null);
      }, MISSION_MS);
    };
    window.addEventListener(MISSION_EVENT, onMission);
    return () => {
      window.removeEventListener(MISSION_EVENT, onMission);
      window.clearTimeout(timer);
    };
  }, []);

  if (!mission) return null;
  return (
    <div className="mission-overlay" aria-hidden="true" data-mission-complete="">
      <div className="mission-stage">
        <div className="mission-reactor">
          <span className="boot-wave mission-wave" />
          <span className="boot-wave mission-wave boot-wave-2" />
          <ArcReactor size={76} />
        </div>
        <p className="mission-title">{mission.title}</p>
        <p className="mission-detail">{mission.detail}</p>
      </div>
    </div>
  );
}
