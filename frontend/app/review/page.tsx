"use client";

import { useState } from "react";
import WeeklyReviewView from "@/components/WeeklyReviewView";
import {
  AccentLine,
  Button,
  Card,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { cx } from "@/lib/ui";
import {
  displayContent,
  generateAction,
  metaCaption,
  reviewView,
  type HistoryItem,
  type WeeklyPayload,
} from "@/lib/weeklyReview";

/** Týdenní přehled (Phase G, vzhled Roadmap 4A): aktuální týden + historie předchozích týdnů (jen ke čtení). */
export default function WeeklyReviewPage() {
  const [selected, setSelected] = useState<string | null>(null); // null = aktuální týden
  const review = useApiResource<WeeklyPayload>(selected ? `/weekly-review/week/${selected}` : "/weekly-review");
  const history = useApiResource<{ items: HistoryItem[] }>("/weekly-review/history");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const data = review.data;

  async function generate(regenerate: boolean) {
    setBusy(true);
    setMessage(null);
    try {
      const payload = await apiJson<WeeklyPayload>("/weekly-review/generate", jsonBody("POST", { regenerate }));
      review.setData(payload);
      void history.reload();
    } catch (err) {
      setMessage(errorMessage(err, "Přehled se nepodařilo vytvořit."));
    } finally {
      setBusy(false);
      setConfirmOpen(false);
    }
  }

  const view = data ? reviewView(data) : null;
  const action = generateAction(data);
  const caption = data ? metaCaption(data) : null;
  const shown = data ? displayContent(data) : { content: null, isFallback: false };
  const items = history.data?.items ?? [];

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={
          <HudLabel>
            Týdenní přehled{data ? ` · ${data.week_label}` : ""}
            {data && !data.is_current ? " · archiv" : ""}
          </HudLabel>
        }
        title="Týdenní přehled"
        subtitle="Pondělí–neděle, pražský čas. Fakta a srovnání jsou spočítaná z dat, odhady jsou označené."
        meta={caption}
        actions={
          <>
            {selected ? (
              <Button variant="ghost" onClick={() => setSelected(null)}>
                ← Aktuální týden
              </Button>
            ) : null}
            {action ? (
              <Button
                variant={action.regenerate ? "secondary" : "primary"}
                busy={busy}
                busyLabel="Vytvářím…"
                onClick={() => (action.regenerate ? setConfirmOpen(true) : void generate(false))}
              >
                {action.label}
              </Button>
            ) : null}
          </>
        }
      />

      {message ? <ErrorState message={message} /> : null}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_16rem] lg:items-start">
        <Card aria-busy={review.loading || busy} className="min-w-0 overflow-hidden p-0 md:p-0">
          <AccentLine />
          <div className="p-4 md:p-6">
            {review.loading ? (
              <LoadingState lines={5} label="Načítám týdenní přehled…" />
            ) : review.status === "error" ? (
              <ErrorState message={review.error} onRetry={() => void review.reload()} />
            ) : (
              <div className="space-y-4">
                {view?.kind === "ready" && view.warning ? (
                  <StatusBadge tone="warning" className="whitespace-normal">{view.warning}</StatusBadge>
                ) : null}
                {view && view.kind !== "ready" ? (
                  <p role="status" className={cx("text-sm", view.kind === "failed" ? "text-warning" : "text-ink-muted")}>
                    {view.kind === "generating" ? "Přehled se právě vytváří…" : view.message}
                  </p>
                ) : null}
                {shown.content ? <WeeklyReviewView content={shown.content} isFallback={shown.isFallback} /> : null}
              </div>
            )}
          </div>
        </Card>

        <Card as="aside" aria-labelledby="history-title" className="lg:sticky lg:top-6">
          <h2 id="history-title" className="mb-3 text-sm font-semibold text-ink">
            Předchozí týdny
          </h2>
          {history.loading ? (
            <LoadingState lines={3} label="Načítám historii…" />
          ) : items.length === 0 ? (
            <EmptyState compact>Zatím žádné uložené přehledy.</EmptyState>
          ) : (
            <ul className="space-y-1.5">
              {items.map((h) => {
                const active = (selected ?? data?.week_start) === h.week_start;
                return (
                  <li key={h.week_start}>
                    <button
                      type="button"
                      aria-current={active ? "true" : undefined}
                      onClick={() => setSelected(h.week_start === data?.week_start && !selected ? null : h.week_start)}
                      className={cx(
                        "motion-press w-full rounded-[var(--radius-control)] border px-3 py-2 text-left text-sm transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                        active ? "border-accent/40 bg-accent/[0.06]" : "border-line-subtle hover:bg-hover",
                      )}
                    >
                      <div className="font-medium text-ink">{h.week_label}</div>
                      <div className="truncate text-xs text-ink-muted">
                        {h.headline ?? (h.status === "failed" ? "nepovedlo se" : h.status === "generating" ? "vytváří se" : "–")}
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Přegenerovat týdenní přehled?"
        message="Vytvoří se nová verze z aktuálních dat (jeden dotaz na AI). Když se nepovede, zůstane ta současná."
        confirmLabel="Přegenerovat"
        busyLabel="Vytvářím…"
        danger={false}
        onConfirm={() => generate(true)}
        onCancel={() => setConfirmOpen(false)}
      />
    </ContentContainer>
  );
}
