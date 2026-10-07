"use client";

import { useId, useState } from "react";
import { GameImage } from "@/components/games/GameImage";
import { Button, Drawer, FormField, StatusBadge, fieldClass } from "@/components/ui";
import { useTankNameForTag } from "@/hooks/useGameAssets";
import { apiFetch, jsonBody, readErrorDetail } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/ui";
import { MASTERY_OPTIONS, masteryLabel, type WotMilestone } from "@/lib/wot";
import {
  MAX_TAGS,
  normalizeTag,
  parserStatusMeta,
  PRESET_TAGS,
  replayDraftFrom,
  replayPatch,
  RESULT_OPTIONS,
  tagLabel,
  toggleTag,
  type ReplayDraft,
  type ReplayErrors,
  type WotReplay,
} from "@/lib/wotReplays";

async function errorText(res: Response): Promise<string> {
  try {
    const body = (await res.clone().json()) as { detail?: { message?: string } | string };
    if (body.detail && typeof body.detail === "object" && body.detail.message) return body.detail.message;
  } catch {
    /* ne-JSON */
  }
  return readErrorDetail(res);
}

/**
 * Úprava metadat replaye. `review` = hned po nahrání: ukáže, co se z replaye načetlo, a nechá to opravit / doplnit.
 * Replay je v tu chvíli už uložený – zavření panelu nic nemaže. Nic není povinné.
 */
export function ReplayForm({
  open,
  replay,
  review,
  milestones,
  knownTanks,
  today,
  onClose,
  onSaved,
}: {
  open: boolean;
  replay: WotReplay | null;
  review?: boolean;
  milestones: WotMilestone[];
  knownTanks: string[];
  today: string;
  onClose: () => void;
  onSaved: (r: WotReplay) => Promise<void> | void;
}) {
  return (
    <Drawer open={open && replay != null} onClose={onClose} title={review ? "Zkontroluj údaje replaye" : "Upravit replay"}>
      {open && replay ? (
        <FormBody key={replay.id} replay={replay} review={review} milestones={milestones} knownTanks={knownTanks} today={today} onClose={onClose} onSaved={onSaved} />
      ) : null}
    </Drawer>
  );
}

function FormBody({
  replay,
  review,
  milestones,
  knownTanks,
  today,
  onClose,
  onSaved,
}: {
  replay: WotReplay;
  review?: boolean;
  milestones: WotMilestone[];
  knownTanks: string[];
  today: string;
  onClose: () => void;
  onSaved: (r: WotReplay) => Promise<void> | void;
}) {
  const ids = { tanks: useId(), tag: useId() };
  const suggested = useTankNameForTag(replay.tank_tag);
  const [draft, setDraft] = useState<ReplayDraft>(() => replayDraftFrom(replay));
  // název z manifestu (podle tagu z replaye) se předvyplní, dokud pole uživatel sám neupraví
  const [tankEdited, setTankEdited] = useState(false);
  const tankValue = tankEdited ? draft.tank_name : draft.tank_name || suggested || "";
  const [errors, setErrors] = useState<ReplayErrors>({});
  const [customTag, setCustomTag] = useState("");
  const [tagError, setTagError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const status = parserStatusMeta(replay.parser_status);

  const set = <K extends keyof ReplayDraft>(k: K, v: ReplayDraft[K]) => setDraft((d) => ({ ...d, [k]: v }));

  function addCustomTag() {
    const tag = normalizeTag(customTag);
    if (!tag) {
      setTagError("Štítek: 1–24 znaků (písmena, číslice, mezera, pomlčka).");
      return;
    }
    if (!draft.tags.includes(tag) && draft.tags.length >= MAX_TAGS) {
      setTagError(`Nejvýš ${MAX_TAGS} štítků.`);
      return;
    }
    setTagError(null);
    setCustomTag("");
    if (!draft.tags.includes(tag)) set("tags", [...draft.tags, tag]);
  }

  /** Uloží rozepsané údaje (bez zavření). `false` = chyba (ukázaná ve formuláři), jinak hotovo. */
  async function persistDraft(): Promise<boolean> {
    const parsed = replayPatch({ ...draft, tank_name: tankValue }, replay, today);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      return false;
    }
    setErrors({});
    if (!Object.keys(parsed.body).length) return true;
    const res = await apiFetch(`/wot/replays/${replay.id}`, jsonBody("PATCH", parsed.body));
    if (!res.ok) throw new Error(await errorText(res));
    await onSaved((await res.json()) as WotReplay);
    return true;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      if (await persistDraft()) onClose();
    } catch (err) {
      setFailure(err instanceof Error && err.message ? err.message : "Uložení se nepodařilo.");
    } finally {
      setBusy(false);
    }
  }

  /** „Vytvořit Mko z tohoto replaye": nejdřív uloží rozepsané údaje, pak server založí Mko z replaye a propojí ho. */
  async function createMilestone() {
    setCreating(true);
    setFailure(null);
    setCreated(null);
    try {
      if (!(await persistDraft())) return;
      const res = await apiFetch(`/wot/replays/${replay.id}/milestone`, { method: "POST" });
      if (!res.ok) throw new Error(await errorText(res));
      const body = (await res.json()) as { replay: WotReplay; milestone: WotMilestone };
      await onSaved(body.replay);
      set("linked_milestone_id", String(body.milestone.id));
      setCreated(`Mko „${body.milestone.tank}" je vytvořené a propojené.`);
    } catch (err) {
      setFailure(err instanceof Error && err.message ? err.message : "Mko se nepodařilo vytvořit.");
    } finally {
      setCreating(false);
    }
  }

  const num = (k: "damage" | "assist" | "kills" | "base_xp", label: string) => (
    <FormField label={label} error={errors[k]}>
      {(p) => <input {...p} inputMode="numeric" value={draft[k]} onChange={(e) => set(k, e.target.value)} className={fieldClass} placeholder="–" />}
    </FormField>
  );
  const customTags = draft.tags.filter((t) => !(PRESET_TAGS as readonly string[]).includes(t));

  return (
    <form onSubmit={submit} noValidate className="space-y-4 p-4" data-testid="replay-form">
      <div className="space-y-1 rounded-[var(--radius-control)] border border-line-subtle bg-surface-2 px-3 py-2" data-parser-status={replay.parser_status}>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
          {review ? <span className="text-xs text-ink-muted">Replay je uložený – údaje můžeš doplnit i později.</span> : null}
        </div>
        <p className="text-xs text-ink-2">{status.hint}</p>
      </div>

      <FormField label="Tank" error={errors.tank_name} hint={replay.tank_tag ? `Z replaye: ${replay.tank_tag}` : "Známý tank dostane obrázek automaticky."}>
        {(p) => (
          <div className="flex items-center gap-3">
            <GameImage kind="tank" name={tankValue || "?"} size="sm" />
            <input
              {...p}
              list={ids.tanks}
              value={tankValue}
              onChange={(e) => {
                setTankEdited(true);
                set("tank_name", e.target.value);
              }}
              className={fieldClass}
              placeholder="např. Progetto 65"
              autoComplete="off"
            />
            <datalist id={ids.tanks}>
              {knownTanks.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </div>
        )}
      </FormField>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField label="Mapa" error={errors.map_name}>
          {(p) => <input {...p} value={draft.map_name} onChange={(e) => set("map_name", e.target.value)} className={fieldClass} placeholder="např. Útesy" />}
        </FormField>
        <FormField label="Datum bitvy" error={errors.played_on}>
          {(p) => <input {...p} type="date" max={today} value={draft.played_on} onChange={(e) => set("played_on", e.target.value)} className={fieldClass} />}
        </FormField>
        {num("damage", "Poškození")}
        {num("assist", "Asistence")}
        {num("kills", "Zničení")}
        {num("base_xp", "Základní XP")}
        <FormField label="Odznak zvládnutí">
          {(p) => (
            <select {...p} value={draft.mastery} onChange={(e) => set("mastery", e.target.value)} className={fieldClass}>
              <option value="">Bez odznaku</option>
              {MASTERY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          )}
        </FormField>
        <FormField label="Výsledek">
          {(p) => (
            <select {...p} value={draft.battle_result} onChange={(e) => set("battle_result", e.target.value)} className={fieldClass}>
              <option value="">Neuvedeno</option>
              {RESULT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          )}
        </FormField>
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-ink-2">Štítky</legend>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Předvolené štítky">
          {PRESET_TAGS.map((t) => {
            const on = draft.tags.includes(t);
            return (
              <button
                key={t}
                type="button"
                aria-pressed={on}
                onClick={() => set("tags", toggleTag(draft.tags, t))}
                className={cx(
                  "motion-press min-h-9 pointer-coarse:min-h-11 rounded-full border px-3 text-xs font-medium",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
                  on ? "border-accent/50 bg-accent/10 text-accent-strong" : "border-line bg-surface-2 text-ink-muted hover:text-ink",
                )}
              >
                {tagLabel(t)}
              </button>
            );
          })}
        </div>
        {customTags.length ? (
          <ul className="flex flex-wrap gap-1.5" aria-label="Vlastní štítky">
            {customTags.map((t) => (
              <li key={t} className="flex items-center gap-1 rounded-full border border-line bg-surface px-2 text-xs text-ink-2">
                {t}
                <Button size="sm" variant="ghost" onClick={() => set("tags", draft.tags.filter((x) => x !== t))} aria-label={`Odebrat štítek ${t}`}>
                  ×
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex gap-2">
          <label htmlFor={ids.tag} className="sr-only">
            Vlastní štítek
          </label>
          <input
            id={ids.tag}
            value={customTag}
            onChange={(e) => setCustomTag(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustomTag();
              }
            }}
            className={cx(fieldClass, "min-w-0 flex-1")}
            placeholder="Vlastní štítek…"
            maxLength={24}
          />
          <Button size="sm" variant="secondary" onClick={addCustomTag}>
            Přidat
          </Button>
        </div>
        {tagError || errors.tags ? (
          <p role="alert" className="text-xs text-danger">
            {tagError || errors.tags}
          </p>
        ) : null}
      </fieldset>

      <FormField label="Propojit s Mkem / milníkem" hint="Nepovinné. Screenshoty milníku se pak ukážou v detailu replaye.">
        {(p) => (
          <select {...p} value={draft.linked_milestone_id} onChange={(e) => set("linked_milestone_id", e.target.value)} className={fieldClass}>
            <option value="">Bez propojení</option>
            {milestones.map((m) => (
              <option key={m.id} value={String(m.id)}>
                {[m.tank, masteryLabel(m.mastery), m.map_name, m.played_on ? formatDate(m.played_on) : null].filter(Boolean).join(" · ")}
              </option>
            ))}
          </select>
        )}
      </FormField>
      {created ? (
        <p role="status" data-testid="replay-milestone-created" className="-mt-2 text-sm text-success">
          {created}
        </p>
      ) : !draft.linked_milestone_id ? (
        <div className="-mt-2 flex flex-wrap items-center gap-x-3 gap-y-2" data-testid="replay-create-milestone">
          {milestones.length === 0 ? <p className="text-sm text-ink-muted">Zatím nemáš žádné Mko.</p> : null}
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void createMilestone()}
            busy={creating}
            busyLabel="Vytvářím…"
            disabled={busy || creating || !(tankValue || replay.tank_tag)}
          >
            Vytvořit Mko z tohoto replaye
          </Button>
        </div>
      ) : null}
      <FormField label="Poznámka" error={errors.notes}>
        {(p) => <textarea {...p} rows={3} value={draft.notes} onChange={(e) => set("notes", e.target.value)} className={fieldClass} placeholder="Co se v bitvě stalo…" />}
      </FormField>
      <label className="flex min-h-11 items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={draft.favorite} onChange={(e) => set("favorite", e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
        <span aria-hidden="true">★</span> Oblíbený replay
      </label>

      {failure ? (
        <p role="alert" className="rounded-[var(--radius-control)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {failure}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2 border-t border-line-subtle pt-4">
        <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…">
          Uložit údaje
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          {review ? "Doplnit později" : "Zrušit"}
        </Button>
      </div>
    </form>
  );
}
