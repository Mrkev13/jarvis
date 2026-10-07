"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useReducer, useRef, useState } from "react";
import { JarvisFigure } from "@/components/jarvis/JarvisFigure";
import { useCompanionPref } from "@/hooks/useJarvisCompanion";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import {
  COMPANION_MIN_VIEWPORT,
  companionAnchors,
  companionBubbleSide,
  companionLayout,
  createCompanion,
  nextCompanionDeadline,
  pickSafeAnchor,
  stepCompanion,
  type CompanionEvent,
  type CompanionMachine,
} from "@/lib/jarvisCompanion";
import { currentJarvisMood, subscribeJarvisSignals } from "@/lib/jarvisSignals";
import { cx } from "@/lib/ui";

/**
 * Jarvis companion (MRK-16): malý robot ve vyhrazeném pruhu dole (jen desktop ≥ 1024 px, když je zapnutý).
 * Logika je celá v `lib/jarvisCompanion.ts`; tady se jen překládá prostředí na události stroje
 * a stroj na DOM. Jediný časovač tiká na `nextCompanionDeadline`.
 */
const WIDE_QUERY = `(min-width: ${COMPANION_MIN_VIEWPORT}px)`;
const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";
const FIELD_SELECTOR = "input, textarea, select, button, a[href], [contenteditable='true'], [tabindex]:not([tabindex='-1'])";

const LABELS = {
  idle: "Jarvis – otevřít AI asistenta",
  walking: "Jarvis – otevřít AI asistenta",
  listening: "Jarvis poslouchá – otevřít AI asistenta",
  thinking: "Jarvis přemýšlí – otevřít AI asistenta",
  success: "Jarvis hlásí úspěch – otevřít AI asistenta",
  warning: "Jarvis čeká na potvrzení – otevřít AI asistenta",
  error: "Jarvis hlásí chybu – otevřít AI asistenta",
  hidden: "",
} as const;

function now(): number {
  return performance.now();
}

function initialMachine(): CompanionMachine {
  return createCompanion({ now: 0, anchors: [], enabled: false, roaming: false });
}

function measureViewport() {
  const sidebar = document.querySelector("[data-desktop-sidebar]")?.getBoundingClientRect().right ?? 0;
  return { width: document.documentElement.clientWidth, height: window.innerHeight, sidebar: Math.round(sidebar) };
}

export function JarvisCompanion() {
  const pathname = usePathname();
  const layout = companionLayout(pathname);
  const { enabled } = useCompanionPref();
  const wide = useMediaQuery(WIDE_QUERY);
  const reduced = useMediaQuery(REDUCED_QUERY);
  const visible = enabled === true && wide === true;

  const [machine, dispatch] = useReducer(
    (m: CompanionMachine, e: CompanionEvent) => stepCompanion(m, e),
    undefined,
    initialMachine,
  );
  const [viewportWidth, setViewportWidth] = useState(0);
  const machineRef = useRef(machine);
  useEffect(() => {
    machineRef.current = machine;
  }, [machine]);

  // vyhrazený pruh dole (CSS `html[data-jarvis-companion="on"]`) – obsah pod Jarvise nikdy nezajede na konci stránky
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.jarvisCompanion = visible ? "on" : "off";
    return () => {
      delete root.dataset.jarvisCompanion;
    };
  }, [visible]);

  useEffect(() => {
    dispatch({ type: "roaming", value: reduced === false, now: now() });
  }, [reduced]);

  useEffect(() => {
    dispatch({ type: "enabled", value: visible, now: now() });
  }, [visible]);

  // kotvy podle viewportu a stránky
  useEffect(() => {
    if (!visible) return;
    const update = () => {
      const vp = measureViewport();
      setViewportWidth(vp.width);
      dispatch({ type: "layout", anchors: companionAnchors(vp, layout), now: now() });
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [visible, layout]);

  // stav aplikace (AI, briefing, Rychlé přidání, grindy)
  useEffect(() => {
    dispatch({ type: "mood", mood: currentJarvisMood(), now: now() });
    return subscribeJarvisSignals((signal) => {
      dispatch(signal.type === "mood" ? { type: "mood", mood: signal.mood, now: now() } : { type: "pulse", kind: signal.kind, now: now() });
    });
  }, []);

  // fokus ovládacího prvku pod Jarvisem → ustoupit na jinou kotvu
  useEffect(() => {
    if (!visible) return;
    const onFocus = (e: FocusEvent) => {
      const target = e.target instanceof Element ? e.target.closest(FIELD_SELECTOR) : null;
      if (!target || target.closest("[data-jarvis-companion-root]")) return;
      const m = machineRef.current;
      const r = target.getBoundingClientRect();
      const heading = m.walk?.target ?? m.pendingTarget ?? m.anchor;
      const safe = pickSafeAnchor(m.anchors, heading, { left: r.left, right: r.right, top: r.top, bottom: r.bottom });
      if (safe) dispatch({ type: "goto", target: safe, now: now() });
    };
    document.addEventListener("focusin", onFocus);
    return () => document.removeEventListener("focusin", onFocus);
  }, [visible]);

  // jediný časovač: tik na nejbližší termín stroje (konec reakce, bubliny, chůze, klidný přesun)
  useEffect(() => {
    const deadline = nextCompanionDeadline(machine);
    if (!Number.isFinite(deadline)) return;
    // setTimeout zaokrouhluje dolů → +1 ms; tik nese aspoň svůj termín, jinak by stroj mohl zůstat viset
    const id = window.setTimeout(
      () => dispatch({ type: "tick", now: Math.max(now(), deadline) }),
      Math.max(0, Math.ceil(deadline - now()) + 1),
    );
    return () => window.clearTimeout(id);
  }, [machine]);

  if (machine.state === "hidden") return null;

  const anchor = machine.anchors.find((a) => a.id === machine.anchor) ?? machine.anchors[0];
  const x = machine.walk ? machine.walk.to : machine.x;
  const y = anchor?.y ?? 0;
  const side = companionBubbleSide(machine.x, viewportWidth);

  return (
    <div
      data-jarvis-companion-root
      data-testid="jarvis-companion"
      data-companion-state={machine.state}
      data-companion-anchor={machine.walk ? `→${machine.walk.target}` : machine.anchor}
      data-companion-facing={machine.facing}
      className="jarvis-companion"
      style={{
        transform: `translate3d(${x}px, ${y}px, 0)`,
        transitionDuration: machine.walk ? `${machine.walk.duration}ms` : "0ms",
      }}
    >
      <div
        // na /ai hlásí stav už samotný chat – bublina by čtečce zněla dvakrát
        role={layout === "ai" ? undefined : "status"}
        aria-live={layout === "ai" ? undefined : "polite"}
        aria-hidden={layout === "ai" ? true : undefined}
        data-testid="jarvis-bubble"
        className={cx("jarvis-bubble-slot", side === "left" ? "right-0" : "left-0")}
      >
        {machine.bubble ? (
          <span key={`${machine.state}-${machine.bubble.until}`} className="jarvis-bubble">
            {machine.bubble.text}
          </span>
        ) : null}
      </div>
      <Link
        href="/ai"
        aria-label={LABELS[machine.state]}
        title="Jarvis – AI asistent"
        data-testid="jarvis-companion-link"
        className="jarvis-companion-hit"
      >
        <span className="jarvis-facing block">
          <JarvisFigure state={machine.state} />
        </span>
      </Link>
    </div>
  );
}

