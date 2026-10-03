"use client";

import { useCallback, useEffect, useState } from "react";
import ConfirmDialog from "@/components/ConfirmDialog";
import WeeklyReviewView from "@/components/WeeklyReviewView";
import { apiFetch } from "@/lib/api";
import { staggerStyle } from "@/lib/motion";
import {
  displayContent,
  generateAction,
  generateErrorText,
  metaCaption,
  reviewView,
  type HistoryItem,
  type WeeklyPayload,
} from "@/lib/weeklyReview";

/** Týdenní přehled (Phase G): aktuální týden + historie předchozích týdnů (jen ke čtení). */
export default function WeeklyReviewPage() {
  const [data, setData] = useState<WeeklyPayload | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null); // null = aktuální týden
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async (week: string | null) => {
    setLoading(true);
    setLoadError(null);
    try {
      const [res, hist] = await Promise.all([
        apiFetch(week ? `/weekly-review/week/${week}` : "/weekly-review"),
        apiFetch("/weekly-review/history"),
      ]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as WeeklyPayload);
      if (hist.ok) setHistory(((await hist.json()) as { items: HistoryItem[] }).items);
    } catch {
      setLoadError("Týdenní přehled se nepodařilo načíst.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load(selected));
  }, [load, selected]);

  async function generate(regenerate: boolean) {
    setConfirmOpen(false);
    setBusy(true);
    setMessage(null);
    try {
      const res = await apiFetch("/weekly-review/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regenerate }),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        setMessage(generateErrorText(res.status, typeof err.detail === "string" ? err.detail : null));
        return;
      }
      setData((await res.json()) as WeeklyPayload);
      void load(null);
    } catch {
      setMessage("Přehled se nepodařilo vytvořit.");
    } finally {
      setBusy(false);
    }
  }

  const view = data ? reviewView(data) : null;
  const action = generateAction(data);
  const caption = data ? metaCaption(data) : null;
  const shown = data ? displayContent(data) : { content: null, isFallback: false };

  return (
    <main className="p-4 md:p-8 max-w-6xl mx-auto space-y-4 md:space-y-6">
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h1 className="text-2xl md:text-4xl font-bold">Týdenní přehled</h1>
          <p className="text-zinc-400 mt-2">
            {data ? `Týden ${data.week_label}` : "Pondělí–neděle, Europe/Prague"}
            {data && !data.is_current ? " · archiv (jen ke čtení)" : ""}
          </p>
          {caption ? <p className="text-xs text-zinc-500 mt-1">{caption}</p> : null}
        </div>
        <div className="flex gap-2 flex-wrap">
          {selected ? (
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="motion-press text-sm px-3 py-2 rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700"
            >
              ← Aktuální týden
            </button>
          ) : null}
          {action ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => (action.regenerate ? setConfirmOpen(true) : void generate(false))}
              className="motion-press text-sm px-3 py-2 rounded-xl border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50"
            >
              {busy ? "Vytvářím…" : action.label}
            </button>
          ) : null}
        </div>
      </header>

      {message ? (
        <p className="text-sm text-zinc-300" aria-live="polite">
          {message}
        </p>
      ) : null}

      <div className="grid gap-4 md:gap-6 lg:grid-cols-[1fr_16rem]">
        <section
          aria-busy={loading || busy}
          className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-6 min-w-0"
          style={staggerStyle(0)}
        >
          {loadError ? (
            <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl p-3 flex items-center justify-between gap-3">
              <span>{loadError}</span>
              <button type="button" onClick={() => void load(selected)} className="motion-press underline underline-offset-2">
                Zkusit znovu
              </button>
            </div>
          ) : !data ? (
            <div className="space-y-3">
              <div className="h-6 w-1/2 rounded bg-zinc-800 animate-pulse" />
              <div className="h-24 rounded-xl bg-zinc-800/60 animate-pulse" />
            </div>
          ) : (
            <div className="space-y-4">
              {view?.kind === "ready" && view.warning ? (
                <p className="text-sm text-amber-200 bg-amber-500/10 border border-amber-400/30 rounded-xl p-2.5">{view.warning}</p>
              ) : null}
              {view && view.kind !== "ready" ? (
                <p role="status" className={`text-sm ${view.kind === "failed" ? "text-amber-200" : "text-zinc-400"}`}>
                  {view.kind === "generating" ? "Přehled se právě vytváří…" : view.message}
                </p>
              ) : null}
              {shown.content ? <WeeklyReviewView content={shown.content} isFallback={shown.isFallback} /> : null}
            </div>
          )}
        </section>

        <aside className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 h-fit" style={staggerStyle(1)}>
          <h2 className="text-sm font-semibold mb-3">Předchozí týdny</h2>
          {history.length === 0 ? (
            <p className="text-sm text-zinc-500">Zatím žádné uložené přehledy.</p>
          ) : (
            <ul className="space-y-1.5">
              {history.map((h) => {
                const active = (selected ?? data?.week_start) === h.week_start;
                return (
                  <li key={h.week_start}>
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => setSelected(h.week_start === data?.week_start && !selected ? null : h.week_start)}
                      className={`motion-press w-full text-left rounded-xl border px-3 py-2 text-sm transition-colors ${
                        active ? "border-violet-400/40 bg-violet-500/10" : "border-zinc-800 hover:bg-zinc-800"
                      }`}
                    >
                      <div className="font-medium">{h.week_label}</div>
                      <div className="text-xs text-zinc-500 truncate">
                        {h.headline ?? (h.status === "failed" ? "nepovedlo se" : h.status === "generating" ? "vytváří se" : "–")}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Přegenerovat týdenní přehled?"
        message="Vytvoří se nová verze z aktuálních dat (jeden dotaz na AI). Když se nepovede, zůstane ta současná."
        confirmLabel="Přegenerovat"
        danger={false}
        onConfirm={() => void generate(true)}
        onCancel={() => setConfirmOpen(false)}
      />
    </main>
  );
}
