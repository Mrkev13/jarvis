"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AccentLine,
  Button,
  Card,
  ConfirmDialog,
  ErrorState,
  HudFrame,
  HudLabel,
  LoadingState,
  StatusBadge,
} from "@/components/ui";
import { useApiResource, type ApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import {
  briefingView,
  fallbackGroups,
  generateAction,
  generatedCaption,
  safeHref,
  type BriefingItem,
  type BriefingPayload,
  type FallbackItem,
} from "@/lib/briefing";
import { cx } from "@/lib/ui";

function MaybeLink({ url, children }: { url: string; children: React.ReactNode }) {
  const href = safeHref(url);
  return href ? (
    <Link
      href={href}
      className="block rounded-[var(--radius-control)] motion-hover-lift focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
    >
      {children}
    </Link>
  ) : (
    <>{children}</>
  );
}

function PriorityRow({ item, n }: { item: BriefingItem; n: number }) {
  return (
    <li>
      <MaybeLink url={item.url}>
        <div className="flex items-start gap-3 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 p-3">
          <span
            className={cx(
              "grid h-7 w-7 shrink-0 place-items-center rounded-full border font-mono text-xs font-semibold tabular-nums",
              n === 1 ? "border-accent/60 bg-accent/15 text-accent-strong" : "border-line text-ink-2",
            )}
          >
            {n}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="break-words font-medium text-ink">{item.text}</span>
              {item.new ? <StatusBadge tone="accent">nové</StatusBadge> : null}
            </div>
            {item.why ? <div className="mt-0.5 break-words text-sm text-ink-2">{item.why}</div> : null}
            {item.when || item.detail ? (
              <div className="mt-0.5 text-xs text-ink-muted">{[item.when, item.detail].filter(Boolean).join(" · ")}</div>
            ) : null}
          </div>
        </div>
      </MaybeLink>
    </li>
  );
}

function SmallRow({ text, when, url, isNew, attention }: { text: string; when?: string; url: string; isNew?: boolean; attention?: boolean }) {
  return (
    <li>
      <MaybeLink url={url}>
        <div
          className={cx(
            "rounded-[var(--radius-control)] border px-3 py-2 text-sm",
            attention ? "border-warning/35 bg-warning/[0.06]" : "border-line-subtle bg-surface-2",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-words text-ink">{text}</span>
            {isNew ? <StatusBadge tone="accent">nové</StatusBadge> : null}
          </div>
          {when ? <div className="mt-0.5 text-xs text-ink-muted">{when}</div> : null}
        </div>
      </MaybeLink>
    </li>
  );
}

function ListBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <HudLabel as="p" className="mb-2">{title}</HudLabel>
      <ul className="space-y-2">{children}</ul>
    </div>
  );
}

function Fallback({ groups }: { groups: { title: string; items: FallbackItem[] }[] }) {
  if (groups.length === 0) return <p className="text-sm text-ink-muted">Podle dat dnes nic nehoří.</p>;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {groups.map((g) => (
        <ListBlock key={g.title} title={g.title}>
          {g.items.map((i) => (
            <SmallRow key={i.ref} text={i.label} when={i.when} url={i.url} attention={g.title.startsWith("Po")} />
          ))}
        </ListBlock>
      ))}
    </div>
  );
}

/**
 * Denní přehled (Phase F, vzhled Roadmap 4A): jeden AI přehled na pražský den, sestavený jen z reálných dat.
 * Hlavní „živý" panel dashboardu → jediné místo s HUD rámečkem. Bez AI přehledu deterministický náhled.
 */
export default function DailyBriefingCard({ index, resource }: { index?: number; resource?: ApiResource<BriefingPayload> }) {
  // Řídicí centrum (Roadmap 4F) předává načtený zdroj – přesun widgetu v rozložení pak nic znovu nenačítá.
  const own = useApiResource<BriefingPayload>(resource ? null : "/briefing/today");
  const briefing = resource ?? own;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const data = briefing.data;

  async function generate(regenerate: boolean) {
    setBusy(true);
    setMessage(null);
    try {
      briefing.setData(await apiJson<BriefingPayload>("/briefing/today/generate", jsonBody("POST", { regenerate })));
    } catch (err) {
      setMessage(errorMessage(err, "Přehled se nepodařilo vytvořit."));
      void briefing.reload();
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  }

  const view = data ? briefingView(data) : null;
  const action = generateAction(data);
  const caption = data ? generatedCaption(data) : null;

  return (
    <HudFrame>
      <Card index={index} aria-labelledby="briefing-title" aria-busy={briefing.loading || busy} className="overflow-hidden p-0 md:p-0">
        <AccentLine />
        <div className="p-4 md:p-5">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <HudLabel as="p" tone="accent">Denní přehled{data?.date ? ` · ${data.date.split("-").reverse().map(Number).join(". ")}` : ""}</HudLabel>
              <h2 id="briefing-title" className="mt-1 text-lg md:text-xl font-semibold text-ink">
                Co je dnes důležité
              </h2>
              {caption ? <p className="mt-0.5 text-xs text-ink-muted">{caption}</p> : null}
            </div>
            {action ? (
              <Button
                size="sm"
                variant="secondary"
                busy={busy}
                busyLabel="Vytvářím…"
                onClick={() => (action.regenerate ? setConfirmOpen(true) : void generate(false))}
              >
                {action.label}
              </Button>
            ) : null}
          </div>

          {briefing.loading ? (
            <LoadingState lines={3} label="Načítám denní přehled…" />
          ) : briefing.status === "error" || !data ? (
            <ErrorState message={briefing.error ?? "Denní přehled se nepodařilo načíst."} onRetry={() => void briefing.reload()} />
          ) : view?.kind === "ready" ? (
            <div className="space-y-4">
              {view.warning ? <StatusBadge tone="warning" className="whitespace-normal">{view.warning}</StatusBadge> : null}
              <p className="max-w-3xl leading-relaxed text-ink-2">{view.content.summary}</p>
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
                        <SmallRow key={w.ref} text={w.text} when={w.when} url={w.url} isNew={w.new} attention />
                      ))}
                    </ListBlock>
                  ) : null}
                  {view.content.upcoming.length > 0 ? (
                    <ListBlock title="Blíží se">
                      {view.content.upcoming.map((u) => (
                        <SmallRow key={u.ref} text={u.text} when={u.when} url={u.url} isNew={u.new} />
                      ))}
                    </ListBlock>
                  ) : null}
                </div>
              ) : null}
              {view.content.note ? <p className="text-sm text-ink-muted">{view.content.note}</p> : null}
            </div>
          ) : (
            <div className="space-y-4">
              <p role="status" className={cx("text-sm", view?.kind === "failed" ? "text-warning" : "text-ink-muted")}>
                {view?.kind === "generating" ? "Přehled se právě vytváří…" : view && "message" in view ? view.message : null}
              </p>
              <Fallback groups={fallbackGroups(data)} />
            </div>
          )}

          {message ? <ErrorState className="mt-3" message={message} /> : null}
        </div>
      </Card>

      <ConfirmDialog
        open={confirmOpen}
        title="Přegenerovat dnešní přehled?"
        message="Vytvoří se nová verze z aktuálních dat (jeden dotaz na AI). Když se nepovede, zůstane ta současná."
        confirmLabel="Přegenerovat"
        busyLabel="Vytvářím…"
        danger={false}
        onConfirm={() => generate(true)}
        onCancel={() => setConfirmOpen(false)}
      />
    </HudFrame>
  );
}
