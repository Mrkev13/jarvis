"use client";

import { useState } from "react";
import { GameImage } from "@/components/games/GameImage";
import { Button, Card, CardHeader, EmptyState, ErrorState, HudLabel, LoadingState, StatusBadge, TextLink, fieldClass } from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { cx } from "@/lib/ui";
import {
  EMPTY_FILTER,
  filterMastery,
  markText,
  masteryOptions,
  sortMastery,
  tierLabel,
  type MasteryFilter,
  type MasteryOverview,
  type MasterySort,
} from "@/lib/wotMastery";

const SORTS: { value: MasterySort; label: string }[] = [
  { value: "tier", label: "Tier" },
  { value: "mark", label: "Odznak" },
  { value: "name", label: "Název" },
  { value: "battles", label: "Bitvy" },
];
const MARK_TONE = { 4: "accent", 3: "success", 2: "info", 1: "neutral", 0: "neutral" } as const;
const SHOWN = 60; // víc řádků až na „Zobrazit vše“ – stovky tanků by stránku zbytečně natáhly

/**
 * MRK-106: M-ka všech tanků z Wargaming API – nejvyšší odznak na tank, filtry (tier, národ, „jen bez M“ = co dohrát)
 * a řazení. Nová M se zapíšou sama do milníků („čeká na replay“); opakovaná M na jednom tanku API nezná.
 */
export function MasteryTable({ onSynced }: { onSynced?: () => void }) {
  const res = useApiResource<MasteryOverview>("/wot/mastery");
  const [filter, setFilter] = useState<MasteryFilter>(EMPTY_FILTER);
  const [sort, setSort] = useState<MasterySort>("tier");
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const data = res.data;
  const configured = data?.config.configured ?? false;
  const rows = data ? sortMastery(filterMastery(data.tanks, filter), sort) : [];
  const options = data ? masteryOptions(data.tanks) : { tiers: [], nations: [] };
  const visible = showAll ? rows : rows.slice(0, SHOWN);

  async function refresh() {
    setBusy(true);
    setNotice(null);
    setError(null);
    try {
      const out = (await apiJson("/wot/mastery/refresh", jsonBody("POST", {}))) as { result: string; message?: string | null; new_aces?: number };
      await res.reload();
      if (out.result === "ok") {
        setNotice(out.new_aces ? `Nová M: ${out.new_aces} – zapsaná do milníků, čekají na replay.` : "Odznaky aktualizované.");
        if (out.new_aces) onSynced?.();
      } else setError(out.message ?? "Synchronizace se nepovedla.");
    } catch (err) {
      setError(errorMessage(err, "Synchronizace se nepovedla."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card as="section" aria-labelledby="wot-mastery-title" data-wot-mastery="">
      <CardHeader
        title={<span id="wot-mastery-title">M-ka všech tanků</span>}
        description="Nejvyšší odznak mistrovství u každého tanku z Wargaming API. Nové M se zapíše samo do milníků."
        actions={
          <Button size="sm" variant="secondary" disabled={!configured || busy} busy={busy} busyLabel="Načítám…" onClick={() => void refresh()}>
            Obnovit
          </Button>
        }
      />
      {error ? <ErrorState message={error} /> : null}
      {notice ? <p role="status" className="mt-2 text-sm text-ink-2">{notice}</p> : null}

      {res.loading ? (
        <LoadingState lines={3} label="Načítám odznaky…" />
      ) : res.status === "error" || !data ? (
        <ErrorState message="Odznaky se nepodařilo načíst." onRetry={() => void res.reload()} />
      ) : !configured && data.tanks.length === 0 ? (
        <EmptyState compact>
          Wargaming API ještě není nastavené. Na serveru doplň do <code>.env.production</code> <code>WG_APPLICATION_ID</code>,{" "}
          <code>WG_REGION</code> a <code>WOT_NICKNAME</code> a restartuj backend – tabulka se pak naplní sama.
        </EmptyState>
      ) : data.tanks.length === 0 ? (
        <EmptyState compact>Zatím nenačteno – server odznaky stáhne nejvýš jednou za 6 h, nebo hned tlačítkem Obnovit.</EmptyState>
      ) : (
        <div className="mt-3 space-y-3">
          <dl className="flex flex-wrap gap-2" aria-label="Souhrn odznaků">
            {(["M", "I", "II", "III", "–"] as const).map((k) => (
              <div key={k} className="flex items-baseline gap-1.5 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-2.5 py-1.5" data-mastery-count={k}>
                <dt className="text-xs text-ink-muted">{k === "–" ? "bez odznaku" : k}</dt>
                <dd className="font-display text-base font-semibold tabular-nums text-ink">{data.summary.by_mark[k]}</dd>
              </div>
            ))}
            {data.summary.pending_replays ? (
              <div className="flex items-center"><StatusBadge tone="info">Čeká na replay: {data.summary.pending_replays}</StatusBadge></div>
            ) : null}
          </dl>

          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_7rem_9rem_8rem] sm:items-end">
            <label className="block text-xs text-ink-muted">
              Hledat tank
              <input value={filter.q} onChange={(e) => setFilter({ ...filter, q: e.target.value })} className={cx(fieldClass, "mt-1")} placeholder="např. Tiger" />
            </label>
            <label className="block text-xs text-ink-muted">
              Tier
              <select aria-label="Tier" value={filter.tier ?? ""} onChange={(e) => setFilter({ ...filter, tier: e.target.value ? Number(e.target.value) : null })} className={cx(fieldClass, "mt-1")}>
                <option value="">Všechny</option>
                {options.tiers.map((t) => <option key={t} value={t}>{tierLabel(t)}</option>)}
              </select>
            </label>
            <label className="block text-xs text-ink-muted">
              Národ
              <select aria-label="Národ" value={filter.nation ?? ""} onChange={(e) => setFilter({ ...filter, nation: e.target.value || null })} className={cx(fieldClass, "mt-1")}>
                <option value="">Všechny</option>
                {options.nations.map((n) => <option key={n.value} value={n.value}>{n.label}</option>)}
              </select>
            </label>
            <label className="block text-xs text-ink-muted">
              Řadit
              <select aria-label="Řadit podle" value={sort} onChange={(e) => setSort(e.target.value as MasterySort)} className={cx(fieldClass, "mt-1")}>
                {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </label>
          </div>
          <label className="inline-flex min-h-10 items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" checked={filter.missingOnly} onChange={(e) => setFilter({ ...filter, missingOnly: e.target.checked })} className="h-4 w-4 accent-[rgb(var(--arc-rgb))]" />
            Jen bez M (co dohrát)
          </label>

          <HudLabel as="p" className="text-ink-muted">{rows.length} z {data.tanks.length} tanků</HudLabel>
          {rows.length ? (
            <ul className="divide-y divide-line-subtle rounded-[var(--radius-control)] border border-line-subtle" aria-label="Odznaky tanků">
              {visible.map((r) => (
                <li key={r.tank_id} className="flex items-center gap-3 px-3 py-2" data-mastery-row={r.tank_id}>
                  <GameImage kind="tank" name={r.name} size="xs" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{r.name}</p>
                    <p className="truncate text-xs text-ink-muted">
                      {[`tier ${tierLabel(r.tier)}`, r.nation_label, r.type_label, r.battles != null ? `${formatNumber(r.battles, 0)} bitev` : null].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                  {r.pending_replay ? (
                    <span className="hidden text-xs sm:inline"><TextLink href="/wot/replays">Nahrát replay</TextLink></span>
                  ) : null}
                  <span className="shrink-0" data-mark={r.mark}>
                    <StatusBadge tone={MARK_TONE[r.mark]}>{markText(r)}</StatusBadge>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState compact>Filtru neodpovídá žádný tank.</EmptyState>
          )}
          {rows.length > SHOWN && !showAll ? (
            <Button size="sm" variant="ghost" onClick={() => setShowAll(true)}>Zobrazit vše ({rows.length})</Button>
          ) : null}
        </div>
      )}
    </Card>
  );
}
