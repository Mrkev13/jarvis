"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui";
import {
  packDesktop,
  SIZE_LABELS,
  visibleWidgets,
  WIDGETS,
  type DashboardLayout,
  type WidgetDef,
  type WidgetSize,
} from "@/lib/dashboardLayout";
import { cx } from "@/lib/ui";

const DEF_BY_ID = new Map(WIDGETS.map((d) => [d.id, d]));

/** Desktop: šířka sloupce bloku (statické třídy kvůli Tailwindu). */
const XL_SPAN: Record<number, string> = { 2: "xl:col-span-2", 3: "xl:col-span-3", 4: "xl:col-span-4", 6: "xl:col-span-6" };
/** Tablet (2 sloupce): malý a střední = půlka, velký a celá šířka = celý řádek. */
const MD_SPAN: Record<WidgetSize, string> = { small: "", medium: "", large: "md:col-span-2", full: "md:col-span-2" };

export interface EditHandlers {
  onMove: (id: string, direction: -1 | 1) => void;
  onSize: (id: string, size: WidgetSize) => void;
  onHide: (id: string) => void;
}

/**
 * Jeden DOM pro všechny šířky (žádné rozložení podle breakpointu v JS → žádný hydration mismatch):
 * - mobil: 1 sloupec, pořadí přes CSS `order`;
 * - tablet: 2 sloupce s `grid-flow-row-dense` (malé karty se doplní vedle sebe jako ve 4B.1);
 * - desktop: bloky z packDesktop() – sloupce s kartami pod sebou, šířky 1/3, 1/2, 2/3, celá.
 * Obaly bloků a sloupců jsou pod desktopem `display: contents`, takže karty patří přímo do mřížky.
 */
export function DashboardGrid({
  layout,
  editing,
  renderWidget,
  handlers,
}: {
  layout: DashboardLayout;
  editing: boolean;
  renderWidget: (id: string, position: number) => React.ReactNode;
  handlers: EditHandlers;
}) {
  const visible = useMemo(() => visibleWidgets(layout), [layout]);
  const blocks = useMemo(() => packDesktop(visible), [visible]);
  const position = useMemo(() => new Map(visible.map((w, i) => [w.id, i])), [visible]);
  const sizeOf = useMemo(() => new Map(visible.map((w) => [w.id, w.size])), [visible]);

  return (
    <div
      data-testid="dashboard-grid"
      data-editing={editing || undefined}
      className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 md:grid-flow-row-dense md:gap-6 xl:flex xl:flex-col xl:items-stretch"
    >
      {blocks.map((block) => (
        <div key={block.columns.map((c) => c.ids.join("+")).join("|")} className="contents xl:grid xl:grid-cols-6 xl:items-start xl:gap-6">
          {block.columns.map((col) => (
            <div key={col.ids.join("+")} className={cx("contents min-w-0 xl:flex xl:flex-col xl:gap-6", XL_SPAN[col.units])}>
              {col.ids.map((id) => {
                const pos = position.get(id) ?? 0;
                const size = sizeOf.get(id) ?? "medium";
                const def = DEF_BY_ID.get(id);
                if (!def) return null;
                return (
                  <div
                    key={id}
                    data-widget={id}
                    data-size={size}
                    style={{ order: pos }}
                    className={cx("min-w-0", MD_SPAN[size])}
                  >
                    {editing ? (
                      <EditableWidget def={def} size={size} position={pos} count={visible.length} handlers={handlers}>
                        {renderWidget(id, pos)}
                      </EditableWidget>
                    ) : (
                      renderWidget(id, pos)
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

/** Režim úprav: ovládací lišta nad kartou; obsah karty je `inert` (žádné omylem otevřené odkazy, Tab jen po ovládání). */
function EditableWidget({
  def,
  size,
  position,
  count,
  handlers,
  children,
}: {
  def: WidgetDef;
  size: WidgetSize;
  position: number;
  count: number;
  handlers: EditHandlers;
  children: React.ReactNode;
}) {
  const labelId = `widget-${def.id}-label`;
  const sizeId = `widget-${def.id}-size`;
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className="rounded-card border border-dashed border-accent/40 bg-accent/[0.03] p-2 md:p-2.5"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2 px-1">
        <div className="flex min-w-0 flex-1 basis-32 items-baseline gap-2">
          <span id={labelId} className="truncate text-sm font-semibold text-ink">
            {def.title}
          </span>
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-ink-faint" aria-label={`pozice ${position + 1} z ${count}`}>
            {position + 1}/{count}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <Button
            size="sm"
            variant="secondary"
            aria-label={`Posunout nahoru: ${def.title}`}
            title="Posunout nahoru"
            data-focus-key={`${def.id}:up`}
            disabled={position === 0}
            onClick={() => handlers.onMove(def.id, -1)}
            className="w-9 px-0 pointer-coarse:w-11"
          >
            <span aria-hidden="true">↑</span>
          </Button>
          <Button
            size="sm"
            variant="secondary"
            aria-label={`Posunout dolů: ${def.title}`}
            title="Posunout dolů"
            data-focus-key={`${def.id}:down`}
            disabled={position === count - 1}
            onClick={() => handlers.onMove(def.id, 1)}
            className="w-9 px-0 pointer-coarse:w-11"
          >
            <span aria-hidden="true">↓</span>
          </Button>
          {def.allowedSizes.length > 1 ? (
            <>
              <label htmlFor={sizeId} className="sr-only">
                Velikost: {def.title}
              </label>
              <select
                id={sizeId}
                value={size}
                data-focus-key={`${def.id}:size`}
                onChange={(e) => handlers.onSize(def.id, e.target.value as WidgetSize)}
                className={cx(
                  "min-h-9 rounded-[var(--radius-control)] border border-line bg-surface-2 px-2 text-sm text-ink [color-scheme:dark]",
                  "hover:border-ink-faint focus:border-accent/70 focus:outline-none focus:ring-2 focus:ring-accent/25 pointer-coarse:min-h-11",
                )}
              >
                {def.allowedSizes.map((s) => (
                  <option key={s} value={s}>
                    {SIZE_LABELS[s]}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            aria-label={`Skrýt widget: ${def.title}`}
            data-focus-key={`${def.id}:hide`}
            onClick={() => handlers.onHide(def.id)}
          >
            Skrýt
          </Button>
        </div>
      </div>
      <div inert className="pointer-events-none select-none opacity-80">
        {children}
      </div>
    </div>
  );
}
