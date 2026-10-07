"use client";

import Image from "next/image";
import { useState } from "react";
import { JarvisEyes, JarvisShellFallback } from "@/components/jarvis/JarvisAvatar";
import type { JarvisState } from "@/lib/jarvisAvatar";
import { jarvisAssetMode } from "@/lib/jarvisAvatar";
import type { CompanionState } from "@/lib/jarvisCompanion";

/**
 * Celá postavička companiona (64 × 84): hlava a trup z MRK-10 `jarvis-shell.svg` (stejná identita jako avatar),
 * pod ní SVG ruce a nohy pro chůzi. Výraz kreslí sdílené `JarvisEyes`. Bez rámečku/dlaždice – volně stojí v UI.
 * Pohyb je čistě v CSS (`app/jarvis-companion.css`, třídy `jarvis-*`), řízený `data-companion-state` na kořeni.
 * Když se obrázek nenačte, hlavu nahradí stejná CSS záloha jako u avatara.
 */
const EXPRESSION: Record<CompanionState, JarvisState> = {
  hidden: "idle",
  idle: "idle",
  walking: "idle",
  listening: "listening",
  thinking: "thinking",
  success: "success",
  warning: "warning",
  error: "error",
};

function Limbs() {
  return (
    <svg aria-hidden="true" viewBox="0 0 64 84" className="jarvis-limbs absolute inset-0 h-full w-full overflow-visible">
      <ellipse className="jarvis-shadow" cx="32" cy="82" rx="17" ry="2.5" fill="#000" opacity=".45" />
      <g className="jarvis-arm jarvis-arm-l">
        <rect x="11" y="47" width="6" height="14" rx="3" fill="#0b1018" stroke="#2a3850" strokeWidth="1" />
        <circle cx="14" cy="61" r="2.6" fill="#111827" stroke="#22cff3" strokeWidth=".8" />
      </g>
      <g className="jarvis-arm jarvis-arm-r">
        <rect x="47" y="47" width="6" height="14" rx="3" fill="#0b1018" stroke="#2a3850" strokeWidth="1" />
        <circle cx="50" cy="61" r="2.6" fill="#111827" stroke="#22cff3" strokeWidth=".8" />
      </g>
      <g className="jarvis-leg jarvis-leg-l">
        <rect x="23" y="60" width="7" height="16" rx="3" fill="#080b11" stroke="#253149" strokeWidth="1" />
        <rect x="20" y="75" width="12" height="5" rx="2.5" fill="#111827" stroke="#2a3850" strokeWidth="1" />
        <path d="M22 78h7" stroke="#2edcff" strokeWidth="1" strokeLinecap="round" />
      </g>
      <g className="jarvis-leg jarvis-leg-r">
        <rect x="34" y="60" width="7" height="16" rx="3" fill="#080b11" stroke="#253149" strokeWidth="1" />
        <rect x="32" y="75" width="12" height="5" rx="2.5" fill="#111827" stroke="#2a3850" strokeWidth="1" />
        <path d="M35 78h7" stroke="#2edcff" strokeWidth="1" strokeLinecap="round" />
      </g>
    </svg>
  );
}

export function JarvisFigure({ state }: { state: CompanionState }) {
  const [assetFailed, setAssetFailed] = useState(false);
  const mode = jarvisAssetMode(assetFailed);
  return (
    <span data-testid="jarvis-figure" data-jarvis-asset={mode} className="jarvis-figure relative block h-[84px] w-16">
      <span className="jarvis-ring" aria-hidden="true" />
      <span className="jarvis-body absolute inset-0">
        <Limbs />
        <span className="jarvis-head absolute left-0 top-0 block h-16 w-16">
          {mode === "asset" ? (
            <Image
              src="/jarvis/jarvis-shell.svg"
              alt=""
              aria-hidden="true"
              fill
              sizes="64px"
              className="object-contain"
              onError={() => setAssetFailed(true)}
            />
          ) : (
            <JarvisShellFallback />
          )}
          <span className="jarvis-eyes absolute inset-0">
            <JarvisEyes state={EXPRESSION[state]} />
          </span>
        </span>
      </span>
    </span>
  );
}
