"use client";

import { Suspense, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ReplayDetail } from "@/components/wot/replays/ReplayDetail";
import { ReplayForm } from "@/components/wot/replays/ReplayForm";
import { ReplayRow } from "@/components/wot/replays/ReplayRow";
import {
  AreaBadge,
  Button,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  ErrorState,
  FilterBar,
  FilterChips,
  FilterSelect,
  HudLabel,
  LoadingState,
  PageHeader,
  PageSection,
  TextLink,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { useGameAssetManifest } from "@/hooks/useGameAssets";
import { apiFetch, jsonBody } from "@/lib/api";
import { plural, pragueDayKey } from "@/lib/format";
import { resolveTankTag } from "@/lib/gameAssets";
import { MASTERY_OPTIONS, type WotMilestone } from "@/lib/wot";
import {
  activeFilterCount,
  DEFAULT_FILTERS,
  duplicateReplayId,
  REPLAY_EXT,
  replayFileError,
  replayQuery,
  REPLAY_HEADER_PEEK_BYTES,
  replayUploadPath,
  replayVehicleTag,
  RESULT_OPTIONS,
  SORT_OPTIONS,
  tagLabel,
  tankTagShort,
  type ReplayFilters,
  type ReplayList,
  type WotReplay,
} from "@/lib/wotReplays";

export default function ReplayLibraryPage() {
  // useSearchParams (?replay=ID z globálního vyhledávání) potřebuje Suspense hranici
  return (
    <Suspense fallback={null}>
      <ReplayLibrary />
    </Suspense>
  );
}

type Notice = { tone: "info" | "danger"; text: string; replayId?: number };

function ReplayLibrary() {
  const router = useRouter();
  const params = useSearchParams();
  const manifest = useGameAssetManifest();
  const [filters, setFilters] = useState<ReplayFilters>(DEFAULT_FILTERS);
  const query = replayQuery(filters);
  const listRes = useApiResource<ReplayList>(`/wot/replays${query ? `?${query}` : ""}`, { debounceMs: 250 });
  const milestonesRes = useApiResource<WotMilestone[]>("/wot/milestones");
  const list = listRes.data;
  const items = list?.items ?? [];
  const milestones = milestonesRes.data ?? [];

  const openParam = params.get("replay");
  const openId = openParam && /^\d{1,10}$/.test(openParam) ? Number(openParam) : null;
  const inList = openId != null ? items.find((r) => r.id === openId) ?? null : null;
  // replay mimo aktuální filtr (odkaz z vyhledávání) → načíst zvlášť
  const single = useApiResource<WotReplay>(openId != null && !inList && list ? `/wot/replays/${openId}` : null);
  const detail = inList ?? (single.data?.id === openId ? single.data : null);

  const [form, setForm] = useState<{ replay: WotReplay; review: boolean } | null>(null);
  const [deleting, setDeleting] = useState<WotReplay | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [todayIso] = useState(() => pragueDayKey(new Date()));
  const fileRef = useRef<HTMLInputElement>(null);

  const setOpen = (id: number | null) => router.replace(id != null ? `/wot/replays?replay=${id}` : "/wot/replays", { scroll: false });
  const update = (patch: Partial<ReplayFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const tankLabel = (value: string) => (value.includes(":") ? (manifest ? resolveTankTag(manifest.tanks, value)?.name : null) ?? tankTagShort(value) ?? value : value);
  const knownTanks = [...new Set([...milestones.map((m) => m.tank), ...(list?.facets.tanks ?? []).filter((t) => !t.includes(":"))])].sort((a, b) => a.localeCompare(b, "cs"));

  async function refresh() {
    await Promise.all([listRes.reload(), openId != null && !inList ? single.reload() : Promise.resolve()]);
  }

  async function upload(file: File) {
    const err = replayFileError(file);
    if (err) {
      setNotice({ tone: "danger", text: err });
      return;
    }
    setUploading(true);
    setNotice(null);
    try {
      // lidský název vozidla z manifestu (Game Enrichment A) podle tagu z hlavičky → server ho uloží pro hledání a Aktivitu
      const tag = replayVehicleTag(new Uint8Array(await file.slice(0, REPLAY_HEADER_PEEK_BYTES).arrayBuffer()));
      const tankName = tag && manifest ? resolveTankTag(manifest.tanks, tag)?.name : null;
      const res = await apiFetch(replayUploadPath(file.name, tankName), { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file });
      const body = (await res.json().catch(() => null)) as unknown;
      if (res.status === 409) {
        const id = duplicateReplayId(body);
        setNotice({ tone: "info", text: "Tenhle replay už v knihovně je – nic se neuložilo podruhé.", replayId: id ?? undefined });
        return;
      }
      if (!res.ok) {
        const detail = (body as { detail?: { message?: string } } | null)?.detail;
        setNotice({ tone: "danger", text: detail?.message ?? "Replay se nepodařilo nahrát." });
        return;
      }
      await listRes.reload();
      setForm({ replay: body as WotReplay, review: true });
    } catch (e) {
      console.error(e);
      setNotice({ tone: "danger", text: "Replay se nepodařilo nahrát." });
    } finally {
      setUploading(false);
    }
  }

  async function toggleFavorite(r: WotReplay) {
    setBusyId(r.id);
    try {
      const res = await apiFetch(`/wot/replays/${r.id}`, jsonBody("PATCH", { favorite: !r.favorite }));
      if (!res.ok) throw new Error("favorite failed");
      await refresh();
    } catch (e) {
      console.error(e);
      setNotice({ tone: "danger", text: "Oblíbení se nepodařilo změnit." });
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    const r = deleting;
    if (!r) return;
    try {
      const res = await apiFetch(`/wot/replays/${r.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 404) throw new Error("delete failed");
      setOpen(null);
      await listRes.reload();
    } catch (e) {
      console.error(e);
      setNotice({ tone: "danger", text: "Replay se nepodařilo smazat." });
    } finally {
      setDeleting(null);
    }
  }

  const uploadButton = (
    <Button variant="primary" size="sm" onClick={() => fileRef.current?.click()} busy={uploading} busyLabel="Nahrávám…">
      Nahrát replay
    </Button>
  );
  const total = list?.total ?? 0;
  const active = activeFilterCount(filters);

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Tanks</HudLabel>}
        title="Knihovna replayů"
        subtitle="Originální .wotreplay soubory památných bitev se štítky a propojením na Mka."
        meta={
          <span className="flex flex-wrap items-center gap-3">
            <AreaBadge area="wot" />
            <TextLink href="/wot">← World of Tanks</TextLink>
          </span>
        }
        actions={uploadButton}
      />
      <input
        ref={fileRef}
        type="file"
        accept={REPLAY_EXT}
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="replay-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) void upload(file);
        }}
      />

      {notice ? (
        <div
          role={notice.tone === "danger" ? "alert" : "status"}
          data-testid="replay-notice"
          className={
            notice.tone === "danger"
              ? "flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
              : "flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-accent/40 bg-accent/5 px-3 py-2 text-sm text-ink"
          }
        >
          <span className="min-w-0 flex-1">{notice.text}</span>
          {notice.replayId ? (
            <Button size="sm" variant="secondary" onClick={() => setOpen(notice.replayId ?? null)}>
              Otevřít existující
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setNotice(null)} aria-label="Zavřít oznámení">
            ×
          </Button>
        </div>
      ) : null}

      {listRes.loading ? (
        <LoadingState lines={4} label="Načítám replaye…" />
      ) : listRes.status === "error" && !list ? (
        <ErrorState message="Knihovnu replayů se nepodařilo načíst." onRetry={() => void listRes.reload()} />
      ) : total === 0 ? (
        <EmptyState action={uploadButton}>
          <span data-testid="replay-empty">Knihovna je zatím prázdná. Nahraj první .wotreplay – originál zůstane uložený a údaje z něj se zkusí načíst.</span>
        </EmptyState>
      ) : (
        <PageSection labelledBy="wot-replays" title={<span id="wot-replays">Replaye</span>}>
          <FilterBar
            label="Filtry replayů"
            search={{ value: filters.q, onChange: (q) => update({ q }), placeholder: "Hledat tank, mapu, poznámku, štítek…", label: "Hledat v replayích" }}
            activeCount={active}
            onReset={() => setFilters(DEFAULT_FILTERS)}
            result={`${items.length} z ${total} ${plural(total, "replaye", "replayů", "replayů")}`}
          >
            <FilterSelect label="Tank" value={filters.tank} onChange={(tank) => update({ tank })}
              options={[{ value: "", label: "Všechny" }, ...(list?.facets.tanks ?? []).map((t) => ({ value: t, label: tankLabel(t) }))]} />
            <FilterSelect label="Mapa" value={filters.map} onChange={(map) => update({ map })}
              options={[{ value: "", label: "Všechny" }, ...(list?.facets.maps ?? []).map((m) => ({ value: m, label: m }))]} />
            <FilterSelect label="Štítek" value={filters.tag} onChange={(tag) => update({ tag })}
              options={[{ value: "", label: "Všechny" }, ...(list?.facets.tags ?? []).map((t) => ({ value: t, label: tagLabel(t) }))]} />
            <FilterSelect label="Odznak" value={filters.mastery} onChange={(mastery) => update({ mastery })}
              options={[{ value: "", label: "Všechny" }, ...MASTERY_OPTIONS.map((o) => ({ value: o.value, label: o.label })), { value: "none", label: "Bez odznaku" }]} />
            <FilterSelect label="Výsledek" value={filters.result} onChange={(result) => update({ result })}
              options={[{ value: "", label: "Všechny" }, ...RESULT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))]} />
            <FilterSelect label="Řazení" value={filters.sort} onChange={(sort) => update({ sort })} options={SORT_OPTIONS.map((o) => ({ value: o.value, label: o.label }))} />
            <FilterChips label="Oblíbené" options={[{ value: "favorite", label: "★ Jen oblíbené" }]} selected={filters.favorite ? ["favorite"] : []}
              onToggle={() => update({ favorite: !filters.favorite })} />
          </FilterBar>
          {items.length === 0 ? (
            <EmptyState action={<Button size="sm" variant="secondary" onClick={() => setFilters(DEFAULT_FILTERS)}>Zrušit filtry</Button>}>
              <span data-testid="replay-no-match">Žádný replay neodpovídá filtrům.</span>
            </EmptyState>
          ) : (
            <EntityList label="Replaye">
              {items.map((r) => (
                <ReplayRow key={r.id} replay={r} busy={busyId === r.id} onOpen={() => setOpen(r.id)} onToggleFavorite={() => void toggleFavorite(r)} />
              ))}
            </EntityList>
          )}
        </PageSection>
      )}

      <ReplayDetail
        replay={detail}
        open={openId != null && detail != null && form == null && deleting == null}
        onClose={() => setOpen(null)}
        onEdit={() => detail && setForm({ replay: detail, review: false })}
        onDelete={() => detail && setDeleting(detail)}
      />
      <ReplayForm
        open={form != null}
        replay={form?.replay ?? null}
        review={form?.review}
        milestones={milestones}
        knownTanks={knownTanks}
        today={todayIso}
        onClose={() => setForm(null)}
        onSaved={async () => {
          await Promise.all([refresh(), milestonesRes.reload()]);
        }}
      />
      <ConfirmDialog
        open={deleting != null}
        title="Smazat replay?"
        message="Smaže se záznam i originální soubor .wotreplay. Propojené Mko zůstane. Tato akce je nevratná."
        confirmLabel="Smazat replay"
        busyLabel="Mažu…"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </ContentContainer>
  );
}
