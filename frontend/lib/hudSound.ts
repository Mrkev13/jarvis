/**
 * MRK-133: zvuky systému Jarvis HUD – syntetické tóny přes Web Audio (žádné soubory, nic se nestahuje).
 * Hrají jen se zapnutou předvolbou „Zvuky systému" (výchozí vypnuto) a tiše (gain ≤ 0,06).
 * Prohlížeč pustí zvuk až po první interakci – do té doby se tón tiše zahodí (AudioContext zůstane suspended).
 */
import { readHudPrefs } from "./hud";

export type HudSound = "boot" | "complete" | "mission";

type Note = { f: number; at: number; dur: number; type?: OscillatorType; gain?: number; to?: number };
const SOUNDS: Record<HudSound, Note[]> = {
  // nabíhající reaktor: klouzavý tón + dva čisté „pingy"
  boot: [
    { f: 180, to: 520, at: 0, dur: 0.55, type: "sine", gain: 0.04 },
    { f: 660, at: 0.45, dur: 0.35, type: "triangle", gain: 0.05 },
    { f: 990, at: 0.62, dur: 0.45, type: "sine", gain: 0.035 },
  ],
  complete: [
    { f: 880, at: 0, dur: 0.12, type: "triangle", gain: 0.05 },
    { f: 1320, at: 0.08, dur: 0.22, type: "sine", gain: 0.04 },
  ],
  mission: [
    { f: 523.25, at: 0, dur: 0.22, type: "triangle", gain: 0.05 },
    { f: 659.25, at: 0.12, dur: 0.22, type: "triangle", gain: 0.05 },
    { f: 783.99, at: 0.24, dur: 0.5, type: "sine", gain: 0.06 },
  ],
};

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    const C = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!C) return null;
    try {
      ctx = new C();
    } catch {
      return null;
    }
  }
  return ctx;
}

export function playHudSound(kind: HudSound, force = false): void {
  if (!force && !readHudPrefs().sounds) return;
  const c = audio();
  if (!c) return;
  if (c.state === "running") return schedule(c, kind);
  // bez předchozí interakce zůstane kontext suspended a tón se tiše nezahraje
  c.resume().then(() => {
    if (c.state === "running") schedule(c, kind);
  }).catch(() => undefined);
}

function schedule(c: AudioContext, kind: HudSound): void {
  const t0 = c.currentTime + 0.02;
  for (const n of SOUNDS[kind]) {
    const osc = c.createOscillator();
    const g = c.createGain();
    osc.type = n.type ?? "sine";
    osc.frequency.setValueAtTime(n.f, t0 + n.at);
    if (n.to) osc.frequency.exponentialRampToValueAtTime(n.to, t0 + n.at + n.dur);
    const peak = n.gain ?? 0.04;
    g.gain.setValueAtTime(0.0001, t0 + n.at);
    g.gain.exponentialRampToValueAtTime(peak, t0 + n.at + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + n.at + n.dur);
    osc.connect(g).connect(c.destination);
    osc.start(t0 + n.at);
    osc.stop(t0 + n.at + n.dur + 0.05);
  }
}

/**
 * Spustí `fn`, jakmile prohlížeč dovolí zvuk/řeč: hned, pokud už stránka měla interakci, jinak při prvním
 * kliknutí / klávese (do `timeoutMs`). Vrací úklid.
 */
export function whenActivated(fn: () => void, timeoutMs = 15000): () => void {
  if (typeof window === "undefined") return () => undefined;
  const ua = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation;
  if (ua?.hasBeenActive) {
    fn();
    return () => undefined;
  }
  let done = false;
  const go = () => {
    if (done) return;
    done = true;
    cleanup();
    fn();
  };
  const timer = window.setTimeout(() => {
    done = true;
    cleanup();
  }, timeoutMs);
  function cleanup() {
    window.clearTimeout(timer);
    window.removeEventListener("pointerdown", go, true);
    window.removeEventListener("keydown", go, true);
  }
  window.addEventListener("pointerdown", go, true);
  window.addEventListener("keydown", go, true);
  return cleanup;
}
