"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import { staggerStyle } from "@/lib/motion";
import { countsLine, reviewView, type WeeklyPayload } from "@/lib/weeklyReview";

/** Kompaktní vstup na dashboardu; celý přehled a historie jsou na /review. */
export default function WeeklyReviewCard({ index = 0 }: { index?: number }) {
  const [data, setData] = useState<WeeklyPayload | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/weekly-review");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as WeeklyPayload);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  const view = data ? reviewView(data) : null;
  return (
    <section
      className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-5"
      style={staggerStyle(index)}
    >
      <div className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <h2 className="text-lg md:text-xl font-semibold flex items-center gap-2">
          <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-indigo-500/15 border border-indigo-400/30 text-indigo-200">
            📅
          </span>
          Týdenní přehled
        </h2>
        <Link href="/review" className="text-sm text-zinc-400 hover:text-zinc-100 transition-colors">
          Otevřít →
        </Link>
      </div>
      {failed ? (
        <p className="text-sm text-zinc-500">Přehled se nepodařilo načíst.</p>
      ) : !data ? (
        <div className="h-12 rounded-xl bg-zinc-800/60 animate-pulse" />
      ) : view?.kind === "ready" ? (
        <div>
          <p className="text-xs text-zinc-500">{data.week_label}</p>
          <p className="font-semibold mt-0.5 break-words">{view.content.headline}</p>
          <p className="text-sm text-zinc-400 mt-1 line-clamp-2">{view.content.summary}</p>
          {countsLine(view.content) ? <p className="text-xs text-zinc-500 mt-2">{countsLine(view.content)}</p> : null}
        </div>
      ) : (
        <p className="text-sm text-zinc-400">
          {view?.kind === "generating" ? "Přehled se právě vytváří…" : view && "message" in view ? view.message : null}
        </p>
      )}
    </section>
  );
}
