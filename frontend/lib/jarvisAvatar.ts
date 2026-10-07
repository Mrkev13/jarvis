export const JARVIS_STATES = ["idle", "listening", "thinking", "success", "warning", "error"] as const;
export const JARVIS_SIZES = ["sm", "md", "lg"] as const;

export type JarvisState = (typeof JARVIS_STATES)[number];
export type JarvisSize = (typeof JARVIS_SIZES)[number];

const VISUALS = {
  idle: { expression: "calm", label: "Jarvis je připraven" },
  listening: { expression: "open", label: "Jarvis poslouchá" },
  thinking: { expression: "focus", label: "Jarvis přemýšlí" },
  success: { expression: "smile", label: "Jarvis hlásí úspěch" },
  warning: { expression: "alert", label: "Jarvis čeká na potvrzení" },
  error: { expression: "cross", label: "Jarvis hlásí chybu" },
} as const;

const PIXELS: Record<JarvisSize, number> = { sm: 40, md: 64, lg: 96 };

export function jarvisVisual(state: JarvisState, size: JarvisSize) {
  return { ...VISUALS[state], pixels: PIXELS[size] };
}

export function jarvisAssetMode(failed: boolean): "asset" | "fallback" {
  return failed ? "fallback" : "asset";
}

export function jarvisMotionClass(state: JarvisState): string {
  if (state === "thinking") return "motion-executing";
  if (state === "success") return "motion-completion";
  if (state === "warning") return "motion-warning";
  if (state === "error") return "motion-error";
  return "";
}

export function aiJarvisState({
  failure,
  failedAction,
  sending,
  confirming,
  listening,
  pending,
  success,
}: {
  failure: boolean;
  failedAction: boolean;
  sending: boolean;
  confirming: boolean;
  listening: boolean;
  pending: number;
  success: boolean;
}): JarvisState {
  if (failure || failedAction) return "error";
  if (sending || confirming) return "thinking";
  if (pending > 0) return "warning";
  if (listening) return "listening";
  if (success) return "success";
  return "idle";
}

export function briefingJarvisState({
  loading,
  busy,
  error,
  generating,
  warning,
}: {
  loading: boolean;
  busy: boolean;
  error: boolean;
  generating: boolean;
  warning: boolean;
}): JarvisState {
  if (error) return "error";
  if (loading || busy || generating) return "thinking";
  if (warning) return "warning";
  return "idle";
}
