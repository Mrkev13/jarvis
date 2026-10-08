"use client";

import { useEffect } from "react";
import { refreshModules } from "@/hooks/useModules";

/**
 * MRK-18 A2: načte runtime stav modulů (GET /modules) při startu aplikace a při návratu do okna,
 * aby se změna z Nastavení na jiném zařízení projevila bez obnovení. Nic nevykresluje.
 */
export function ModuleRuntimeLoader() {
  useEffect(() => {
    void refreshModules();
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshModules();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  return null;
}
