"use client";

import { useState } from "react";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  FormField,
  fieldClass,
  MetricCard,
  PageSection,
  StatGrid,
  StatusBadge,
} from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { staggerStyle } from "@/lib/motion";
import {
  sparkPoints,
  syncedAgo,
  validateWish,
  weekTrend,
  WISH_KINDS,
  type WowCollections,
  type WowCounts,
  type WowWish,
  type WowWishKind,
} from "./lib";

const REFRESH_TEXT: Record<string, string> = {
  ok: "Sbírka aktualizovaná.",
  skipped: "Sbírka je aktuální.",
  no_character: "Sbírka se čte přes postavu – nejdřív přidej postavu, která se načte z API.",
  not_configured: "WoW API není na serveru nastavené.",
  unavailable: "Blizzard API teď sbírku nevrátilo, zkus to později.",
};

const TILES: { key: keyof WowCounts; label: string }[] = [
  { key: "mounts", label: "Mounti" },
  { key: "pets", label: "Mazlíčci" },
  { key: "achievements", label: "Achievementy" },
  { key: "achievement_points", label: "Achievement body" },
];

/**
 * MRK-128: sbírka účtu – počty mountů, mazlíčků a achievementů s vývojem za týden (denní snapshot z Blizzard API)
 * a seznam „chci získat“, který se odškrtává sám, jakmile API položku ukáže.
 */
export function Collections({ data, configured, onChanged }: { data: WowCollections; configured: boolean; onChanged: () => Promise<unknown> }) {
  const [kind, setKind] = useState<WowWishKind>("mount");
  const [name, setName] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(key: string, fn: () => Promise<string | null>) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      const msg = await fn();
      await onChanged();
      if (msg) setNotice(msg);
      return true;
    } catch (err) {
      setError(errorMessage(err, "Akce se nepovedla."));
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const invalid = validateWish(kind, name);
    setFormError(invalid);
    if (invalid) return;
    const clean = name.trim().replace(/\s+/g, " ");
    const ok = await act("add", async () => {
      const res = (await apiJson("/wow/wishes", jsonBody("POST", { kind, name: clean }))) as { already_owned?: boolean };
      return res?.already_owned ? `${clean} už ve sbírce máš – rovnou odškrtnuto.` : `${clean} přidán do seznamu.`;
    });
    if (ok) setName("");
  }

  const latest = data.latest;
  const open = data.wishes.filter((w) => !w.acquired);
  const done = data.wishes.filter((w) => w.acquired);

  return (
    <PageSection
      labelledBy="wow-collections"
      title="Sbírka"
      description={latest ? `Celý účet · aktualizováno ${syncedAgo(latest.updated_at)}` : "Celý účet – mounti, mazlíčci a achievementy z Blizzard API."}
      actions={
        <Button size="sm" variant="secondary" disabled={!configured || busy !== null} busy={busy === "refresh"} busyLabel="Načítám…"
          onClick={() => void act("refresh", async () => {
            const res = (await apiJson("/wow/collections/refresh", jsonBody("POST", {}))) as { result?: string };
            return REFRESH_TEXT[res?.result ?? ""] ?? "Hotovo.";
          })}>
          Obnovit sbírku
        </Button>
      }
    >
      <div className="space-y-4" data-wow-collections="">
        {error ? <ErrorState message={error} /> : null}
        {notice ? <p role="status" className="text-sm text-ink-2">{notice}</p> : null}

        {latest ? (
          <StatGrid cols={4}>
            {TILES.map((t) => {
              const trend = weekTrend(data.week[t.key]);
              const points = sparkPoints(data.history, t.key);
              return (
                <div key={t.key} className="relative" data-wow-count={t.key}>
                  <MetricCard
                    label={t.label}
                    value={latest[t.key] == null ? "–" : formatNumber(latest[t.key] as number, 0)}
                    trend={trend?.text}
                    trendTone={trend?.tone}
                    className="wow-count"
                  />
                  {points ? (
                    <svg aria-hidden="true" viewBox="0 0 120 32" preserveAspectRatio="none" className="wow-spark pointer-events-none absolute inset-x-3 bottom-2 h-6 w-[calc(100%-1.5rem)]">
                      <polyline points={points} fill="none" />
                    </svg>
                  ) : null}
                </div>
              );
            })}
          </StatGrid>
        ) : (
          <EmptyState compact>
            {configured ? "Sbírka se načte při další obnově (nejvýš jednou za 6 h) – nebo hned tlačítkem Obnovit sbírku." : "Po nastavení Blizzard API se tu ukáže počet mountů, mazlíčků a achievementů."}
          </EmptyState>
        )}

        <Card as="section" aria-labelledby="wow-wishes" data-wow-wishes="">
          <CardHeader
            as="h3"
            title={<span id="wow-wishes">Chci získat</span>}
            description="Mount, mazlíček nebo achievement – anglicky, jak ho píše hra. Odškrtne se sám, až ho API ukáže."
          />
          <form onSubmit={add} className="grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-end" noValidate>
            <FormField label="Druh">
              {(p) => (
                <select {...p} value={kind} onChange={(e) => setKind(e.target.value as WowWishKind)} className={fieldClass}>
                  {WISH_KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
                </select>
              )}
            </FormField>
            <FormField label="Název" error={formError ?? undefined}>
              {(p) => <input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder="Invincible's Reins" className={fieldClass} autoComplete="off" />}
            </FormField>
            <Button type="submit" variant="primary" busy={busy === "add"} busyLabel="Přidávám…">Přidat</Button>
          </form>

          {data.wishes.length ? (
            <EntityList label="Chci získat" className="mt-4">
              {[...open, ...done].map((w, i) => (
                <WishRow key={w.id} w={w} idx={i} busy={busy === `del-${w.id}`}
                  onDelete={() => void act(`del-${w.id}`, async () => {
                    await apiJson(`/wow/wishes/${w.id}`, { method: "DELETE" });
                    return `${w.name} odebrán ze seznamu.`;
                  })} />
              ))}
            </EntityList>
          ) : (
            <EmptyState compact className="mt-4">Seznam je prázdný – přidej, po čem jdeš.</EmptyState>
          )}
        </Card>
      </div>
    </PageSection>
  );
}

function WishRow({ w, idx, busy, onDelete }: { w: WowWish; idx: number; busy: boolean; onDelete: () => void }) {
  return (
    <EntityRow
      rowKey={`wowwish-${w.id}`}
      searchTarget={`wowwish-${w.id}`}
      style={staggerStyle(idx)}
      className="motion-card"
      tone={w.acquired ? "success" : "neutral"}
      muted={w.acquired}
      busy={busy}
      badges={
        <>
          <StatusBadge tone="neutral">{w.kind_label}</StatusBadge>
          {w.acquired ? <StatusBadge tone="success" dot>Získáno</StatusBadge> : <StatusBadge tone="info">Chybí</StatusBadge>}
        </>
      }
      title={w.name}
      meta={w.acquired && w.acquired_at ? `Získáno ${syncedAgo(w.acquired_at)}` : "Čeká na API"}
      actions={
        <Button size="sm" variant="ghost" busy={busy} onClick={onDelete} aria-label={`Odebrat: ${w.name}`}>
          Odebrat
        </Button>
      }
    />
  );
}
