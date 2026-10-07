"use client";

import Image from "next/image";
import { useState } from "react";
import {
  jarvisAssetMode,
  jarvisMotionClass,
  jarvisVisual,
  type JarvisSize,
  type JarvisState,
} from "@/lib/jarvisAvatar";
import { cx } from "@/lib/ui";

const ACCENT: Record<JarvisState, string> = {
  idle: "#2edcff",
  listening: "#65e7ff",
  thinking: "#2edcff",
  success: "#34d399",
  warning: "#fbbf24",
  error: "#fb7185",
};

function Eyes({ state }: { state: JarvisState }) {
  const color = ACCENT[state];
  return (
    <svg aria-hidden="true" viewBox="0 0 180 180" className="pointer-events-none absolute inset-0 h-full w-full">
      <g fill="none" stroke={color} strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" style={{ filter: `drop-shadow(0 0 5px ${color})` }}>
        {state === "idle" ? <><path d="M61 84h18" /><path d="M103 84h18" /></> : null}
        {state === "listening" ? <><path d="M70 77v15" /><path d="M112 77v15" /><path strokeWidth="3" opacity=".7" d="M34 78v20M146 78v20" /></> : null}
        {state === "thinking" ? <><path d="M61 86h18" /><path d="M105 81h14" /></> : null}
        {state === "success" ? <><path d="M59 88q10-17 20 0" /><path d="M103 88q10-17 20 0" /></> : null}
        {state === "warning" ? <><path d="M61 84h18" /><path d="M103 84h18" /></> : null}
        {state === "error" ? <><path d="m61 78 17 17m0-17L61 95" /><path d="m104 78 17 17m0-17-17 17" /></> : null}
      </g>
      {state === "thinking" ? (
        <g fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }}><circle cx="76" cy="44" r="3" /><circle cx="90" cy="41" r="3" /><circle cx="104" cy="44" r="3" /></g>
      ) : null}
      {state === "warning" ? (
        <g fill={color} style={{ filter: `drop-shadow(0 0 4px ${color})` }}><rect x="135" y="43" width="5" height="16" rx="2.5" /><circle cx="137.5" cy="65" r="3" /></g>
      ) : null}
      {state === "success" ? <path d="m137 52 5 5 10-12" fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" /> : null}
    </svg>
  );
}

function ShellFallback() {
  return (
    <div data-testid="jarvis-fallback" className="absolute inset-[17%] rounded-[38%] border border-cyan-300/35 bg-slate-950 shadow-[inset_0_8px_18px_rgba(41,75,110,.35)]">
      <div className="absolute -top-[18%] left-[8%] h-[28%] w-[76%] -rotate-6 rounded-t-[70%] rounded-br-full border border-slate-600 bg-slate-900" />
      <div className="absolute -bottom-[31%] left-[8%] h-[35%] w-[84%] rounded-t-[45%] border border-slate-700 bg-slate-950" />
    </div>
  );
}

export function JarvisAvatar({
  state = "idle",
  size = "md",
  decorative = true,
  label,
  className,
}: {
  state?: JarvisState;
  size?: JarvisSize;
  decorative?: boolean;
  label?: string;
  className?: string;
}) {
  const [assetFailed, setAssetFailed] = useState(false);
  const visual = jarvisVisual(state, size);
  const mode = jarvisAssetMode(assetFailed);
  const accessibleLabel = label ?? visual.label;

  return (
    <span
      data-testid="jarvis-avatar"
      data-jarvis-state={state}
      data-jarvis-size={size}
      data-jarvis-asset={mode}
      aria-hidden={decorative ? "true" : undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : accessibleLabel}
      className={cx(
        "relative isolate inline-block shrink-0 overflow-hidden rounded-[34%] bg-slate-950/75 ring-1 ring-cyan-300/15",
        jarvisMotionClass(state),
        className,
      )}
      style={{ width: visual.pixels, height: visual.pixels }}
    >
      {mode === "asset" ? (
        <Image
          src="/jarvis/jarvis-shell.svg"
          alt=""
          aria-hidden="true"
          fill
          sizes={`${visual.pixels}px`}
          className="object-contain"
          onError={() => setAssetFailed(true)}
          priority={size === "md"}
        />
      ) : (
        <ShellFallback />
      )}
      <Eyes state={state} />
    </span>
  );
}
