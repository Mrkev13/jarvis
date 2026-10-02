"use client";

import { useState } from "react";
import { AnimatedNumber } from "@/components/motion/AnimatedNumber";
import { StreakFlame } from "@/components/motion/StreakFlame";
import { staggerStyle, useCompletionSignal, useIncreaseSignal, useNewIds } from "@/lib/motion";

const formatInt = (v: number) => new Intl.NumberFormat("cs-CZ").format(Math.round(v));
const PENDING_STATES = ["pending", "executing", "failed", "success", "rejected"] as const;
type PendingState = (typeof PENDING_STATES)[number];

function Section({ title, index, children }: { title: string; index: number; children: React.ReactNode }) {
  return (
    <section className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-5" style={staggerStyle(index)}>
      <h2 className="text-lg font-semibold mb-4">{title}</h2>
      {children}
    </section>
  );
}

function PendingStateDemo({ state }: { state: PendingState }) {
  if (state === "success" || state === "rejected") {
    return (
      <div
        className={`motion-outcome rounded-2xl border px-4 py-3 text-sm flex items-center gap-2 ${
          state === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : "border-zinc-700 bg-zinc-800/60 text-zinc-300"
        }`}
      >
        <span aria-hidden="true">{state === "success" ? "✓" : "↩"}</span>
        <span className="font-medium">{state === "success" ? "Potvrzeno" : "Zrušeno"}:</span>
        <span>Přidat výdaj 300 Kč</span>
      </div>
    );
  }
  const tone =
    state === "failed"
      ? "motion-shake border-red-500/50 from-red-500/10"
      : state === "executing"
        ? "motion-executing border-sky-500/40 from-sky-500/10"
        : "border-amber-500/30 from-amber-500/10";
  return (
    <div className={`relative overflow-hidden border bg-gradient-to-br via-zinc-900/80 to-zinc-900/80 rounded-2xl p-4 ${tone}`}>
      <div className="text-[11px] uppercase tracking-wider font-semibold text-zinc-300">
        {state === "failed" ? "Provedení selhalo" : state === "executing" ? "Provádím změnu…" : "Standa AI chce provést změnu"}
      </div>
      <div className="font-semibold mt-1">Přidat výdaj 300 Kč</div>
    </div>
  );
}

/** Izolovaná ukázka motion primitiv (jen pro vývoj, route /dev/motion s MOTION_PREVIEW=1). */
export function MotionPreview() {
  const [progress, setProgress] = useState(40);
  const completion = useCompletionSignal(progress);
  const [amount, setAmount] = useState(14138);
  const [unread, setUnread] = useState(2);
  const pulse = useIncreaseSignal(unread, true);
  const [rows, setRows] = useState([1, 2, 3]);
  const fresh = useNewIds(rows, true);
  const [done, setDone] = useState(false);
  const [pendingState, setPendingState] = useState<PendingState>("pending");
  const [pendingKey, setPendingKey] = useState(0);

  return (
    <main className="p-4 md:p-8 max-w-5xl mx-auto space-y-5">
      <h1 className="text-2xl md:text-3xl font-bold">Motion preview</h1>

      <Section title="Streak plamen" index={0}>
        <div className="flex flex-wrap items-center gap-6">
          <StreakFlame days={0} broken />
          <StreakFlame days={3} />
          <StreakFlame days={7} />
          <StreakFlame days={30} size="lg" />
        </div>
      </Section>

      <Section title="Progress + dokončení" index={1}>
        <div className="flex items-center gap-3">
          <div className="flex-1 h-3 bg-zinc-800 rounded-full overflow-hidden">
            <div className="motion-progress h-full bg-emerald-500" style={{ width: `${progress}%` }} />
          </div>
          <div key={completion} className={`w-14 text-right tabular-nums rounded-md ${completion > 0 ? "motion-complete" : ""}`}>
            <AnimatedNumber value={progress} format={formatInt} /> %
          </div>
        </div>
        <div className="flex gap-2 mt-3">
          <button className="motion-press px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setProgress((p) => Math.min(100, p + 30))}>+30 %</button>
          <button className="motion-press px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setProgress(40)}>Reset</button>
        </div>
      </Section>

      <Section title="Čísla, puls, nový řádek" index={2}>
        <div className="flex flex-wrap items-center gap-4">
          <span className="text-2xl font-bold text-amber-200"><AnimatedNumber value={amount} format={formatInt} /> Kč</span>
          <button className="motion-press px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setAmount((a) => a + 2437)}>+2 437 Kč</button>
          <span key={pulse} className={`inline-flex px-2 py-0.5 rounded-full text-xs bg-amber-500/20 border border-amber-500/40 text-amber-200 ${pulse > 0 ? "motion-pulse" : ""}`}>
            🔔 {unread}
          </span>
          <button className="motion-press px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setUnread((u) => u + 1)}>+1 upozornění</button>
        </div>
        <div className="space-y-2 mt-4">
          {rows.map((r) => (
            <div key={r} className={`rounded-xl border border-zinc-800 bg-zinc-950/40 px-3 py-2 ${fresh.has(String(r)) ? "motion-highlight" : ""}`}>
              Transakce #{r}
            </div>
          ))}
        </div>
        <button className="motion-press mt-2 px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setRows((rs) => [Math.max(...rs) + 1, ...rs])}>Přidat řádek</button>
      </Section>

      <Section title="Úkol: hotovo / po termínu, hover" index={3}>
        <div className="space-y-2">
          <div className={`motion-done-transition rounded-xl border border-zinc-800 bg-zinc-950/40 px-3 py-2 ${done ? "motion-done" : ""}`}>
            Esej o ústavě {done ? "(done)" : "(todo)"}
          </div>
          <div className="motion-attention rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2">Po termínu (3 pulzy, pak klid)</div>
          <a href="#" className="motion-hover-lift block rounded-xl border border-zinc-800 bg-zinc-950/40 px-3 py-2 hover:border-zinc-600">Klikací karta (hover lift)</a>
        </div>
        <button className="motion-press mt-2 px-3 py-1.5 rounded-lg bg-zinc-800" onClick={() => setDone((d) => !d)}>Přepnout hotovo</button>
      </Section>

      <Section title="AI pending akce – stavy" index={4}>
        <div className="flex flex-wrap gap-2 mb-3">
          {PENDING_STATES.map((s) => (
            <button
              key={s}
              className={`motion-press px-3 py-1.5 rounded-lg ${pendingState === s ? "bg-zinc-600" : "bg-zinc-800"}`}
              onClick={() => {
                setPendingState(s);
                setPendingKey((k) => k + 1);
              }}
            >
              {s}
            </button>
          ))}
        </div>
        <PendingStateDemo key={pendingKey} state={pendingState} />
      </Section>
    </main>
  );
}
