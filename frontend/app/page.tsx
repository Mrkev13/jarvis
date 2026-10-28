"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { DashboardGrid } from "@/components/dashboard/DashboardGrid";
import { WIDGET_COMPONENTS, type DashboardPayload, type DayTimelinePayload, type TodayResource } from "@/components/dashboard/widgets";
import { MODULE_WIDGET_COMPONENTS } from "@/modules/registry";
import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  ErrorState,
  HudLabel,
  LoadingState,
  PageHeader,
  StatusPulse,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { useDashboardLayout } from "@/hooks/useDashboardLayout";
import type { BriefingPayload } from "@/lib/briefing";
import type { ChangesResponse } from "@/lib/changes";
import { changesPreviewPath } from "@/lib/controlCenter";
import { normalizeToday } from "@/lib/today";
import {
  hiddenWidgets,
  isDefaultLayout,
  moveWidget,
  needsDashboardData,
  needsToday,
  setWidgetSize,
  setWidgetVisible,
  SIZE_LABELS,
  visiblePosition,
  WIDGETS,
  type WidgetId,
  type WidgetSize,
} from "@/lib/dashboardLayout";
import type { WeeklyPayload } from "@/lib/weeklyReview";

const TITLE = new Map(WIDGETS.map((w) => [w.id, w.title]));

/**
 * Řídicí centrum (Roadmap 4F): widgety z explicitního registru (lib/dashboardLayout.ts) v uživatelském
 * rozložení (pořadí, viditelnost, velikost). „Upravit dashboard" zapne režim úprav; změny platí a ukládají se
 * hned, „Hotovo" režim jen ukončí.
 * MRK-78: hlavní denní obrazovka – nahoře „Co hoří" a „Můj den" (jádro /today), rozložení uložené na serveru
 * (platí na PC i v mobilu). /today a /review zůstávají za odkazy z karet.
 */
export default function Home() {
  const { layout, update, reset, available, syncError, retrySync } = useDashboardLayout();
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState(false); // po prvních úpravách už se vstupní animace karet nepřehrávají
  const [confirmReset, setConfirmReset] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [focusKey, setFocusKey] = useState<string | null>(null);

  const isVisible = (id: WidgetId) => Boolean(layout?.widgets.some((w) => w.id === id && w.visible));
  // Jeden GET /dashboard pro všechny widgety; jen když je některý z nich vidět. Přehledy jen když jsou vidět.
  const dashboard = useApiResource<DashboardPayload>(layout && needsDashboardData(layout) ? "/dashboard" : null);
  const briefing = useApiResource<BriefingPayload>(isVisible("daily_briefing") ? "/briefing/today" : null);
  const weekly = useApiResource<WeeklyPayload>(isVisible("weekly_review") ? "/weekly-review" : null);
  // MRK-78: jeden GET /today pro „Co hoří" i „Můj den"; volno z denní osy (až je znám pražský den ze serveru)
  const todayRaw = useApiResource<unknown>(layout && needsToday(layout) ? "/today" : null);
  const todayData = useMemo(() => (todayRaw.data ? normalizeToday(todayRaw.data) : null), [todayRaw.data]);
  const today: TodayResource = { ...todayRaw, data: todayData };
  const dayTimeline = useApiResource<DayTimelinePayload>(
    isVisible("day") && todayData?.date ? `/timeline/day?date=${todayData.date}&min_minutes=30` : null,
  );
  const [changesPath] = useState(() => changesPreviewPath()); // okno „od včera" se počítá jednou při otevření
  const changes = useApiResource<ChangesResponse>(isVisible("changes") ? changesPath : null);

  // fokus po přesunu / skrytí / ukončení úprav (prvek se mohl přemístit do jiného bloku → nový uzel)
  useEffect(() => {
    if (!focusKey) return;
    const el = document.querySelector<HTMLElement>(`[data-focus-key="${focusKey}"]`);
    if (el && !(el as HTMLButtonElement).disabled) el.focus();
    else if (focusKey.endsWith(":up") || focusKey.endsWith(":down")) {
      // na okraji je směrové tlačítko zakázané → druhé
      const other = focusKey.endsWith(":up") ? focusKey.replace(/:up$/, ":down") : focusKey.replace(/:down$/, ":up");
      document.querySelector<HTMLElement>(`[data-focus-key="${other}"]`)?.focus();
    }
    queueMicrotask(() => setFocusKey(null));
  }, [focusKey, layout, editing]);

  const handlers = {
    onMove: useCallback(
      (id: string, direction: -1 | 1) => {
        let result = "";
        update((l) => {
          const next = moveWidget(l, id, direction);
          const pos = visiblePosition(next, id);
          result = `${TITLE.get(id)}: pozice ${pos.index} z ${pos.count}.`;
          return next;
        });
        setAnnouncement(result);
        setFocusKey(`${id}:${direction < 0 ? "up" : "down"}`);
      },
      [update],
    ),
    onSize: useCallback(
      (id: string, size: WidgetSize) => {
        update((l) => setWidgetSize(l, id, size));
        setAnnouncement(`${TITLE.get(id)}: velikost ${SIZE_LABELS[size].toLowerCase()}.`);
        setFocusKey(`${id}:size`);
      },
      [update],
    ),
    onHide: useCallback(
      (id: string) => {
        update((l) => setWidgetVisible(l, id, false));
        setAnnouncement(`${TITLE.get(id)} skryt. Vrátíš ho v sekci Skryté widgety.`);
        setFocusKey(`${id}:show`);
      },
      [update],
    ),
  };

  function show(id: string) {
    update((l) => setWidgetVisible(l, id, true));
    setAnnouncement(`${TITLE.get(id)} je zpět na dashboardu.`);
    setFocusKey(`${id}:hide`);
  }

  function startEditing() {
    setEditing(true);
    setEdited(true);
    setFocusKey("dashboard:done");
  }

  function finishEditing() {
    setEditing(false);
    setAnnouncement("Úpravy dashboardu ukončeny.");
    setFocusKey("dashboard:edit");
  }

  const hidden = layout ? hiddenWidgets(layout) : [];
  const allHidden = layout !== null && hidden.length === layout.widgets.length;
  const dashboardLoading = dashboard.loading || (layout !== null && needsDashboardData(layout) && dashboard.status === "idle");

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={
          <HudLabel className="flex items-center gap-2">
            <StatusPulse tone="success" live={!dashboard.loading && !dashboard.error} /> Standa Hub · řídicí centrum
          </HudLabel>
        }
        title="Řídicí centrum"
        // na mobilu bez podtitulku: první obrazovka patří „Co hoří" a další položce dne (MRK-78/95)
        subtitle={<span className="hidden md:inline">Co hoří, co tě dnes čeká a co se změnilo – na jednom místě.</span>}
        actions={
          editing ? (
            <>
              <Button variant="ghost" onClick={() => setConfirmReset(true)} disabled={!layout || isDefaultLayout(layout, available)}>
                Obnovit výchozí rozložení
              </Button>
              <Button variant="primary" onClick={finishEditing} data-focus-key="dashboard:done">
                Hotovo
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={startEditing} disabled={!layout} data-focus-key="dashboard:edit">
                Upravit dashboard
              </Button>
              {dashboard.status !== "idle" ? (
                <Button variant="secondary" onClick={() => void dashboard.reload()} busy={dashboard.refreshing} busyLabel="Obnovuji…">
                  Obnovit
                </Button>
              ) : null}
            </>
          )
        }
      />

      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>

      {editing ? (
        <div
          role="note"
          className="mb-4 rounded-[var(--radius-control)] border border-accent/30 bg-accent/5 px-4 py-3 text-sm text-ink-2 md:mb-6"
        >
          <HudLabel as="span" tone="accent" className="mr-2">
            Režim úprav
          </HudLabel>
          Šipkami měníš pořadí, výběrem velikost, „Skrýt“ widget schová. Změny se ukládají hned.
        </div>
      ) : null}

      {syncError ? (
        <p role="status" className="mb-4 flex flex-wrap items-center gap-2 text-sm text-warning md:mb-6">
          Rozložení se nepodařilo synchronizovat se serverem – zatím platí jen na tomto zařízení.
          <Button size="sm" variant="ghost" onClick={retrySync}>
            Zkusit znovu
          </Button>
        </p>
      ) : null}

      {dashboard.status === "error" ? (
        <ErrorState message={dashboard.error} onRetry={() => void dashboard.reload()} retrying={dashboard.refreshing} />
      ) : dashboard.error ? (
        <ErrorState message={`Obnovení selhalo: ${dashboard.error}`} />
      ) : null}

      {layout === null ? (
        <LoadingState lines={4} label="Načítám rozložení…" />
      ) : allHidden && !editing ? (
        <EmptyState
          action={
            <Button variant="primary" onClick={startEditing} data-focus-key="dashboard:edit">
              Upravit dashboard
            </Button>
          }
        >
          Všechny widgety jsou skryté.
        </EmptyState>
      ) : (
        <DashboardGrid
          layout={layout}
          editing={editing}
          handlers={handlers}
          renderWidget={(id, position) => {
            // jádro / starší moduly, pak widgety modulů z modules/registry.tsx (MRK-21)
            const Widget = WIDGET_COMPONENTS[id as WidgetId] ?? MODULE_WIDGET_COMPONENTS[id];
            return Widget ? (
              <Widget
                data={dashboard.data}
                loading={dashboardLoading}
                index={edited ? undefined : position}
                briefing={briefing}
                weekly={weekly}
                today={today}
                changes={changes}
                dayTimeline={dayTimeline}
              />
            ) : null;
          }}
        />
      )}

      {editing && layout ? (
        <Card aria-labelledby="hidden-widgets-title" className="mt-4 md:mt-6">
          <CardHeader title={<span id="hidden-widgets-title">Skryté widgety</span>} icon="folder" />
          {hidden.length ? (
            <ul className="flex flex-wrap gap-2" aria-label="Skryté widgety">
              {hidden.map((w) => (
                <li key={w.id}>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => show(w.id)}
                    aria-label={`Zobrazit widget: ${TITLE.get(w.id)}`}
                    data-focus-key={`${w.id}:show`}
                  >
                    <span aria-hidden="true">+</span> {TITLE.get(w.id)}
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState compact>Žádné skryté widgety – všechno je na dashboardu.</EmptyState>
          )}
        </Card>
      ) : null}

      <ConfirmDialog
        open={confirmReset}
        title="Obnovit výchozí rozložení?"
        message="Pořadí, viditelnost i velikosti widgetů se vrátí do původního stavu. Data se nemění."
        confirmLabel="Obnovit výchozí"
        danger={false}
        onConfirm={() => {
          reset();
          setConfirmReset(false);
          setAnnouncement("Výchozí rozložení obnoveno.");
          setFocusKey("dashboard:done");
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </ContentContainer>
  );
}
