"use client";

import { useEffect } from "react";
import { pragueHour } from "@/lib/boot";
import { daypartFor } from "@/lib/hud";

/**
 * MRK-133: barva HUD podle denní doby (pražský čas) – nastaví `data-daypart` na <html>; app/hud.css podle něj mění
 * jen záři a mřížku pozadí (akcenty a kontrast textu zůstávají). Přepočet jednou za 10 minut, nic nevykresluje.
 */
export function DaypartTint() {
  useEffect(() => {
    const apply = () => {
      document.documentElement.dataset.daypart = daypartFor(pragueHour());
    };
    apply();
    const t = window.setInterval(apply, 10 * 60 * 1000);
    return () => window.clearInterval(t);
  }, []);
  return null;
}
