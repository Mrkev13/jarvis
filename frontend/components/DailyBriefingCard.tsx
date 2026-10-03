"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import ConfirmDialog from "@/components/ConfirmDialog";
import { apiFetch } from "@/lib/api";
import {
  briefingView,
  fallbackGroups,
  generateAction,
  generatedCaption,
  generateErrorText,
  safeHref,
  type BriefingItem,
  type BriefingPayload,
  type FallbackItem,
} from "@/lib/briefing";
import { staggerStyle } from "@/lib/motion";

function MaybeLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = safeHref(url);
  return href ? (
    <Link href={href} className="block rounded-xl motion-hover-lift">
      {children}
    </Link>
  ) : (
    <>{children}</>
  );
}

function NewBadge() {
  return (
    <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded-full border bg-sky-500/10 border-sky-400/30 text-sky-200">
      nové
    </span>
  );
}

function PriorityRow({ item, n }: { item: BriefingItem; n: number }) {
  return (
    <li>
      <MaybeLink url={item.url}>
        <div className="rounded-xl border border-zinc-800 bg-zinc-950/40 p-3 flex items-start gap-3">
          <div
            className={`shrink-0 w-8 h-8 rounded-full grid place-items-center font-bold text-sm border ${n === 1 ? "bg-amber-400/90 text-zinc-950 border-amber-300" : "bg-white/5 text-zinc-100 border-white/10"}`}
          >
            {n}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-[15px] leading-snug break-words">{item.text}</span>
              {item.new ? <NewBadge /> : null}
            </div>
            {item.why ? <div className="text-sm text-zinc-400 mt-1 break-words">{item.why}</div> : null}
            {item.when || item.detail ? (
              <div className="text-xs text-zinc-500 mt-1">{[item.when, item.detail].filter(Boolean).join(" · ")}</div>
            ) : null}
          </div>
        </div>
      </MaybeLink>
    </li>
  );
}

function SmallRow({ text, when, url, isNew, tone }: { text: string; when?: string; url: string; isNew?: boolean; tone: "warn" | "plain" }) {
  return (
    <li>
      <MaybeLink url={url}>
        <div
          className={`rounded-xl border p-2.5 text-sm ${tone === "warn" ? "bg-red-500/10 border-red-400/30" : "bg-zinc-950/40 border-zinc-800"}`}
        >
          <div className="flex items-center gap-2 flex-wrap">
            <span className="break-words text-zinc-100">{text}</span>
            {isNew ? <NewBadge /> : null}
          </div>
          {when ? <div className="text-xs text-zinc-500 mt-0.5">{when}</div> : null}
        </div>
      </MaybeLink>
    </li>
  );
}

function ListBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <h3 className="text-xs uppercase tracking-wide text-zinc-500 mb-2">{title}</h3>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function Fallback({ groups }: { groups: { title: string; items: FallbackItem[] }[] }) {
  if (groups.length === 0) {
    return <p className="text-sm text-zinc-500">Podle dat dnes nic nehoří.</p>;
  }
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {groups.map((g) => (
        <ListBlock key={g.title} title={g.title}>
          {g.items.map((i) => (
            <SmallRow key={i.ref} text={i.label} when={i.when} url={i.url} tone={g.title.startsWith("Po") ? "warn" : "plain"} />
          ))}
        </ListBlock>
      ))}
    </div>
  );
}

/**
 * Denní přehled (Phase F): jeden AI přehled na pražský den, sestavený jen z reálných dat.
 * Bez AI přehledu ukazuje deterministický náhled (dnes / po termínu / brzy).
 */
export default function DailyBriefingCard({ index = 0 }: { index?: number }) {
  const [data, setData] = useState<BriefingPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await apiFetch("/briefing/today");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData((await res.json()) as BriefingPayload);
    } catch {
      setLoadError("Denní přehled se nepodařilo načíst.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function generate(regenerate: boolean) {
    setConfirmOpen(false);
    setBusy(true);
    setMessage(null);
    try {
      const res = await apiFetch("/briefing/today/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ regenerate }),
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        setMessage(generateErrorText(res.status, typeof err.detail === "string" ? err.detail : null));
        if (res.status === 409) void load();
        return;
      }
      setData((await res.json()) as BriefingPayload);
    } catch {
      setMessage("Přehled se nepodařilo vytvořit.");
    } finally {
      setBusy(false);
    }
  }

  const view = data ? briefingView(data) : null;
  const action = generateAction(data);
  const caption = data ? generatedCaption(data) : null;

  return (
    <section
      aria-busy={loading || busy}
      className="motion-card bg-zinc-900 border border-zinc-800 rounded-2xl p-4 md:p-5"
      style={staggerStyle(index)}
    >
      <div className="flex items-start justify-between gap-3 mb-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-lg md:text-xl font-semibold flex items-center gap-2">
            <span className="inline-grid h-7 w-7 place-items-center rounded-xl bg-violet-500/15 border border-violet-400/30 text-violet-200">
              🧭
            </span>
            Denní přehled
          </h2>
          {caption ? <p className="text-xs text-zinc-500 mt-1">{caption}</p> : null}
        </div>
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

      {loadError ? (
        <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-xl p-3 flex items-center justify-between gap-3">
          <span>{loadError}</span>
          <button type="button" onClick={() => void load()} className="motion-press underline underline-offset-2">
            Zkusit znovu
          </button>
        </div>
      ) : !data ? (
        <div className="space-y-3">
          <div className="h-4 w-2/3 rounded bg-zinc-800 animate-pulse" />
          <div className="h-16 rounded-xl bg-zinc-800/60 animate-pulse" />
        </div>
      ) : view?.kind === "ready" ? (
        <div className="space-y-4">
          {view.warning ? (
            <p className="text-sm text-amber-200 bg-amber-500/10 border border-amber-400/30 rounded-xl p-2.5">{view.warning}</p>
          ) : null}
          <p className="text-zinc-200 leading-relaxed">{view.content.summary}</p>
          {view.content.priorities.length > 0 ? (
            <ListBlock title="Priority">
              {view.content.priorities.map((p, i) => (
                <PriorityRow key={p.ref} item={p} n={i + 1} />
              ))}
            </ListBlock>
          ) : null}
          {view.content.watch.length > 0 || view.content.upcoming.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2">
              {view.content.watch.length > 0 ? (
                <ListBlock title="Pozor / po termínu">
                  {view.content.watch.map((w) => (
                    <SmallRow key={w.ref} text={w.text} when={w.when} url={w.url} isNew={w.new} tone="warn" />
                  ))}
                </ListBlock>
              ) : null}
              {view.content.upcoming.length > 0 ? (
                <ListBlock title="Blíží se">
                  {view.content.upcoming.map((u) => (
                    <SmallRow key={u.ref} text={u.text} when={u.when} url={u.url} isNew={u.new} tone="plain" />
                  ))}
                </ListBlock>
              ) : null}
            </div>
          ) : null}
          {view.content.note ? <p className="text-sm text-zinc-400">{view.content.note}</p> : null}
        </div>
      ) : (
        <div className="space-y-4">
          <p
            role="status"
            className={`text-sm ${view?.kind === "failed" ? "text-amber-200" : "text-zinc-400"}`}
          >
            {view?.kind === "generating" ? "Přehled se právě vytváří…" : view && "message" in view ? view.message : null}
          </p>
          <Fallback groups={fallbackGroups(data)} />
        </div>
      )}

      {message ? (
        <p className="text-sm text-zinc-300 mt-3" aria-live="polite">
          {message}
        </p>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Přegenerovat dnešní přehled?"
        message="Vytvoří se nová verze z aktuálních dat (jeden dotaz na AI). Když se nepovede, zůstane ta současná."
        confirmLabel="Přegenerovat"
        danger={false}
        onConfirm={() => void generate(true)}
        onCancel={() => setConfirmOpen(false)}
      />
    </section>
  );
}
