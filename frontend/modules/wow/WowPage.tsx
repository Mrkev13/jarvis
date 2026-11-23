"use client";

import { HudCore } from "@/components/jarvis/HudCore";
import { wowCore } from "@/lib/hudModules";
import { useState } from "react";
import {
  ActionMenu,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ContentContainer,
  EmptyState,
  EntityList,
  EntityRow,
  ErrorState,
  FormField,
  fieldClass,
  HudLabel,
  LoadingState,
  MetricCard,
  PageHeader,
  PageSection,
  Progress,
  StatGrid,
  StatusBadge,
} from "@/components/ui";
import { useApiResource } from "@/hooks/useApiResource";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { staggerStyle } from "@/lib/motion";
import {
  batchMessage,
  levelLabel,
  professionLabel,
  syncedAgo,
  syncTone,
  targetProgress,
  validateCharacterForm,
  isForeverNamespace,
  type WowBatchResult,
  type WowCharacter,
  type WowOverview,
} from "./lib";

type ActionResult = { result?: string; message?: string | null };

/**
 * World of Warcraft (MRK-127): sledované postavy (alti) se snapshotem z Blizzard API – level, třída, item level,
 * profese a postup k cílovému levelu. Data obnovuje server sám (nejvýš jednou za 6 h) nebo tlačítkem Obnovit.
 */
export default function WowPage() {
  const wow = useApiResource<WowOverview>("/wow");
  const [name, setName] = useState("");
  const [realm, setRealm] = useState("");
  const [target, setTarget] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [removeTarget, setRemoveTarget] = useState<WowCharacter | null>(null);
  const [editTarget, setEditTarget] = useState<{ id: number; value: string } | null>(null);

  const data = wow.data;
  const configured = data?.config.configured ?? false;
  // MRK-130: WoW Forever nemá realmy – formulář chce jméno + příjmení a pole Realm skryje
  const forever = isForeverNamespace(data?.config.namespace);

  async function run(id: number | null, path: string, init: RequestInit, ok?: string): Promise<boolean> {
    setBusyId(id);
    setActionError(null);
    setNotice(null);
    try {
      const res = (await apiJson(path, init)) as ActionResult | undefined;
      await wow.reload();
      if (res && res.result && res.result !== "ok" && res.message) setNotice(res.message);
      else if (ok) setNotice(ok);
      return true;
    } catch (err) {
      setActionError(errorMessage(err, "Akce se nepovedla."));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  // Codex review #91: hromadná obnova má vlastní tvar odpovědi – úspěch jen když se něco opravdu načetlo
  async function refreshAll() {
    setBusyId(-1);
    setActionError(null);
    setNotice(null);
    try {
      const res = (await apiJson("/wow/refresh", jsonBody("POST", {}))) as WowBatchResult;
      await wow.reload();
      const msg = batchMessage(res);
      if (msg.tone === "success") setNotice(msg.text);
      else setActionError(msg.text);
    } catch (err) {
      setActionError(errorMessage(err, "Obnova se nepovedla."));
    } finally {
      setBusyId(null);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    const invalid = validateCharacterForm(name, forever ? "" : realm, target);
    setFormError(invalid);
    if (invalid) return;
    setSaving(true);
    const ok = await run(null, "/wow/characters", jsonBody("POST", {
      name: name.trim(), realm: forever ? "" : realm.trim(), target_level: target.trim() ? Number(target) : null,
    }), `Postava ${name.trim()} přidaná.`);
    setSaving(false);
    if (ok) {
      setName("");
      setTarget("");
    }
  }

  function renderRow(c: WowCharacter, idx: number) {
    const pct = targetProgress(c);
    const busy = busyId === c.id;
    const editing = editTarget?.id === c.id;
    return (
      <EntityRow
        key={c.id}
        rowKey={`wow-${c.id}`}
        searchTarget={`wowchar-${c.id}`}
        style={staggerStyle(idx)}
        className="motion-card"
        busy={busy}
        badges={
          <>
            <StatusBadge tone={syncTone(c.sync_status)} dot={c.sync_status === "ok"}>{c.sync_label}</StatusBadge>
            {c.class_name ? <StatusBadge tone="neutral">{c.class_name}</StatusBadge> : null}
            {c.at_target ? <StatusBadge tone="success">Cíl splněn</StatusBadge> : null}
          </>
        }
        title={c.name}
        meta={[c.race_name, c.active_spec, c.realm_name, c.item_level != null ? `ilvl ${c.item_level}` : null]
          .filter(Boolean).join(" · ") || c.realm_name}
        actions={
          editing ? (
            <form
              className="flex items-center gap-2"
              onSubmit={async (e) => {
                e.preventDefault();
                const value = editTarget?.value.trim() ?? "";
                const n = value ? Number(value) : null;
                if (n != null && (!Number.isInteger(n) || n < 1 || n > 100)) {
                  setActionError("Cílový level: 1–100.");
                  return;
                }
                if (await run(c.id, `/wow/characters/${c.id}`, jsonBody("PATCH", { target_level: n }), "Cíl uložen.")) setEditTarget(null);
              }}
            >
              <input
                aria-label={`Cílový level: ${c.name}`}
                inputMode="numeric"
                value={editTarget?.value ?? ""}
                onChange={(e) => setEditTarget({ id: c.id, value: e.target.value })}
                className={`${fieldClass} w-20`}
              />
              <Button size="sm" variant="primary" type="submit" busy={busy}>Uložit</Button>
              <Button size="sm" variant="ghost" type="button" onClick={() => setEditTarget(null)}>Zpět</Button>
            </form>
          ) : (
            <>
              <Button size="sm" variant="secondary" disabled={busy || !configured} busy={busy} busyLabel="Načítám…"
                onClick={() => void run(c.id, `/wow/characters/${c.id}/refresh`, jsonBody("POST", {}), `${c.name} aktualizovaná.`)}>
                Obnovit<span className="sr-only">: {c.name}</span>
              </Button>
              <ActionMenu
                icon="more"
                variant="ghost"
                ariaLabel={`Další akce: ${c.name}`}
                disabled={busy}
                items={[
                  { label: "Cílový level", ariaLabel: `Nastavit cílový level: ${c.name}`, onSelect: () => setEditTarget({ id: c.id, value: c.target_level ? String(c.target_level) : "" }) },
                  { label: "Přestat sledovat", ariaLabel: `Přestat sledovat: ${c.name}`, tone: "danger", onSelect: () => setRemoveTarget(c) },
                ]}
              />
            </>
          )
        }
      >
        <div className="mt-2 space-y-1.5">
          <p className="text-sm text-ink-2" data-wow-level="">{levelLabel(c)}</p>
          {pct != null ? <Progress value={pct} label={`${c.name}: postup k cílovému levelu`} size="sm" tone={c.at_target ? "success" : undefined} /> : null}
          {c.professions.length ? (
            <p className="text-xs text-ink-muted">Profese: {c.professions.map(professionLabel).join(", ")}</p>
          ) : null}
          <p className="text-xs text-ink-faint">{c.last_synced_at ? `Aktualizováno ${syncedAgo(c.last_synced_at)}` : "Zatím nenačteno"}</p>
        </div>
      </EntityRow>
    );
  }

  return (
    <ContentContainer>
      <PageHeader
        eyebrow={<HudLabel>Modul · World of Warcraft</HudLabel>}
        title="World of Warcraft"
        subtitle="Alti na jednom místě – level, třída, item level a kolik zbývá do cíle. Data z Blizzard API."
        actions={
          data && data.characters.length > 0 ? (
            <Button variant="secondary" disabled={!configured || busyId !== null} busy={busyId === -1} busyLabel="Obnovuji…"
              onClick={() => void refreshAll()}>
              Obnovit vše
            </Button>
          ) : null
        }
      />

      {actionError ? <ErrorState message={actionError} /> : null}
      {notice ? <p role="status" className="text-sm text-ink-2">{notice}</p> : null}

      {wow.loading ? (
        <LoadingState lines={4} label="Načítám postavy…" />
      ) : wow.status === "error" || !data ? (
        <ErrorState message={wow.error} onRetry={() => void wow.reload()} />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
          <div className="min-w-0 space-y-6">
            {!configured ? (
              <Card data-wow-setup="">
                <CardHeader title="Blizzard API ještě není nastavené" description="Bez klíčů jdou postavy přidat, ale data se nenačtou." />
                <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-ink-2">
                  <li>Na develop.battle.net si vytvoř API client (zdarma).</li>
                  <li>Na serveru doplň do <code>.env.production</code> <code>BATTLENET_CLIENT_ID</code> a <code>BATTLENET_CLIENT_SECRET</code> (případně <code>WOW_NAMESPACE</code> – Classic, WoW Forever <code>profile-forever-eu</code>).</li>
                  <li>Restartuj backend (<code>restart-v3.sh</code>) – postavy se pak načtou samy.</li>
                </ol>
              </Card>
            ) : null}

            {/* MRK-134: „flotila" altů – kolik postav je na cílovém levelu */}
            <HudCore module="wow" label="Jarvis · flotila altů" {...wowCore(data.summary)} />

            <StatGrid cols={3}>
              <MetricCard label="Postav" value={data.summary.characters} />
              <MetricCard label="Nejvyšší level" value={data.summary.max_level || "–"} />
              <MetricCard label="Na cílovém levelu" value={`${data.summary.at_target}/${data.summary.with_target}`} hint="z postav s cílem" />
            </StatGrid>

            <PageSection labelledBy="wow-characters" title="Postavy">
              {data.characters.length ? (
                <EntityList label="WoW postavy">{data.characters.map(renderRow)}</EntityList>
              ) : (
                <EmptyState compact>Zatím žádná postava. Přidej první vpravo – stačí {forever ? "jméno a příjmení" : "jméno a realm"}.</EmptyState>
              )}
            </PageSection>
          </div>

          <Card as="section" aria-labelledby="wow-add">
            <CardHeader as="h2" title={<span id="wow-add">Přidat postavu</span>} description={forever ? "Jméno a příjmení jako ve hře (WoW Forever nemá realmy); level a zbytek se načte z API." : "Jméno a realm jako ve hře; level a zbytek se načte z API."} />
            <form onSubmit={add} className="space-y-3" noValidate>
              <FormField label="Jméno postavy" hint={forever ? "Jméno i příjmení, např. Zareth Malgrave" : undefined} error={formError && formError.startsWith("Jméno") ? formError : undefined}>
                {(p) => <input {...p} value={name} onChange={(e) => setName(e.target.value)} placeholder={forever ? "Zareth Malgrave" : "Thrall"} className={fieldClass} autoComplete="off" />}
              </FormField>
              {forever ? null : (
                <FormField label="Realm" hint="Název serveru, např. Pyrewood Village (WoW Forever: místo realmu jméno a příjmení)" error={formError && formError.includes("realm") ? formError : undefined}>
                  {(p) => <input {...p} value={realm} onChange={(e) => setRealm(e.target.value)} className={fieldClass} autoComplete="off" />}
                </FormField>
              )}
              <FormField label="Cílový level" hint="Nepovinné – např. 60" error={formError && formError.startsWith("Cílový") ? formError : undefined}>
                {(p) => <input {...p} value={target} inputMode="numeric" onChange={(e) => setTarget(e.target.value)} className={fieldClass} />}
              </FormField>
              <Button type="submit" variant="primary" busy={saving} busyLabel="Přidávám…" className="w-full">
                Přidat postavu
              </Button>
            </form>
          </Card>
        </div>
      )}

      <ConfirmDialog
        open={removeTarget !== null}
        title="Přestat sledovat postavu?"
        message={removeTarget ? `${removeTarget.name} zmizí z Hubu. Ve hře se nic nemění; historie levelů v Aktivitě zůstane.` : undefined}
        confirmLabel="Přestat sledovat"
        cancelLabel="Ponechat"
        busyLabel="Odebírám…"
        onConfirm={async () => {
          const t = removeTarget;
          if (t) await run(t.id, `/wow/characters/${t.id}`, { method: "DELETE" }, `${t.name} už se nesleduje.`);
          setRemoveTarget(null);
        }}
        onCancel={() => setRemoveTarget(null)}
      />
    </ContentContainer>
  );
}
