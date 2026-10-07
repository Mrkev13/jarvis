"use client";

import { useId, useState } from "react";
import { GameImage } from "@/components/games/GameImage";
import { Button, Drawer, FormField, fieldClass } from "@/components/ui";
import { apiFetch, jsonBody, readErrorDetail } from "@/lib/api";
import { cx } from "@/lib/ui";
import {
  emptyMilestoneDraft,
  MASTERY_OPTIONS,
  milestoneBody,
  milestoneDraftFrom,
  screenshotFileError,
  screenshotUploadPath,
  SCREENSHOT_TYPES,
  type MilestoneDraft,
  type MilestoneErrors,
  type WotMilestone,
} from "@/lib/wot";

type Pending = { key: string; file: File; caption: string };

/** Detail 4xx z backendu ({error, message}) → text. */
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
 * Přidání / úprava milníku („Mko") v postranním panelu. Povinný je jen tank; obrázek tanku se doplní sám
 * (Game Enrichment A). Screenshoty: nové se nahrají po uložení milníku (jeden po druhém), existujícím jde změnit
 * popisek nebo je odebrat. Částečné selhání nahrávání = milník zůstane uložený, panel ukáže, co se nepovedlo.
 */
export function MilestoneForm({
  open,
  milestone,
  knownTanks,
  today,
  onClose,
  onSaved,
}: {
  open: boolean;
  milestone: WotMilestone | null;
  knownTanks: string[];
  today: string;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  return (
    <Drawer open={open} onClose={onClose} title={milestone ? "Upravit milník" : "Nové Mko / milník"}>
      {open ? <FormBody key={milestone?.id ?? "new"} milestone={milestone} knownTanks={knownTanks} today={today} onClose={onClose} onSaved={onSaved} /> : null}
    </Drawer>
  );
}

function FormBody({
  milestone,
  knownTanks,
  today,
  onClose,
  onSaved,
}: {
  milestone: WotMilestone | null;
  knownTanks: string[];
  today: string;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const ids = { tanks: useId(), files: useId() };
  const [saved, setSaved] = useState<WotMilestone | null>(milestone);
  const [draft, setDraft] = useState<MilestoneDraft>(() => (milestone ? milestoneDraftFrom(milestone) : emptyMilestoneDraft()));
  const [errors, setErrors] = useState<MilestoneErrors>({});
  const [captions, setCaptions] = useState<Record<number, string>>(() =>
    Object.fromEntries((milestone?.screenshots ?? []).map((s) => [s.id, s.caption ?? ""])),
  );
  const [removed, setRemoved] = useState<Set<number>>(new Set());
  const [pending, setPending] = useState<Pending[]>([]);
  const [fileErrors, setFileErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const set = <K extends keyof MilestoneDraft>(k: K, v: MilestoneDraft[K]) => setDraft((d) => ({ ...d, [k]: v }));

  function addFiles(list: FileList | null) {
    if (!list) return;
    const errs: string[] = [];
    const next: Pending[] = [];
    for (const file of Array.from(list)) {
      const err = screenshotFileError(file);
      if (err) errs.push(err);
      else next.push({ key: `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`, file, caption: "" });
    }
    setFileErrors(errs);
    setPending((p) => [...p, ...next]);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const parsed = milestoneBody(draft, today);
    if (!parsed.ok) {
      setErrors(parsed.errors);
      return;
    }
    setErrors({});
    setBusy(true);
    setFailure(null);
    try {
      const res = saved
        ? await apiFetch(`/wot/milestones/${saved.id}`, jsonBody("PATCH", parsed.body))
        : await apiFetch("/wot/milestones", jsonBody("POST", parsed.body));
      if (!res.ok) throw new Error(await errorText(res));
      const m = (await res.json()) as WotMilestone;
      setSaved(m);
      const problems: string[] = [];
      for (const id of removed) {
        const r = await apiFetch(`/wot/screenshots/${id}`, { method: "DELETE" });
        if (!r.ok && r.status !== 404) problems.push(`Screenshot se nepodařilo odebrat (${await errorText(r)}).`);
      }
      for (const s of milestone?.screenshots ?? []) {
        if (removed.has(s.id) || (captions[s.id] ?? "") === (s.caption ?? "")) continue;
        const r = await apiFetch(`/wot/screenshots/${s.id}`, jsonBody("PATCH", { caption: captions[s.id] || null }));
        if (!r.ok) problems.push(`Popisek se nepodařilo uložit (${await errorText(r)}).`);
      }
      const left: Pending[] = [];
      for (const p of pending) {
        const r = await apiFetch(screenshotUploadPath(m.id, p.file.name, p.caption), {
          method: "POST",
          headers: { "Content-Type": p.file.type || "application/octet-stream" },
          body: p.file,
        });
        if (!r.ok) {
          problems.push(`${p.file.name}: ${await errorText(r)}`);
          left.push(p);
        }
      }
      setPending(left);
      setRemoved(new Set());
      await onSaved();
      if (problems.length) {
        setFailure(`Milník je uložený, ale: ${problems.join(" ")}`);
      } else {
        onClose();
      }
    } catch (err) {
      setFailure(err instanceof Error && err.message ? err.message : "Uložení se nepodařilo.");
    } finally {
      setBusy(false);
    }
  }

  const num = (k: "damage" | "assist" | "kills" | "base_xp", label: string) => (
    <FormField label={label} error={errors[k]}>
      {(p) => <input {...p} inputMode="numeric" value={draft[k]} onChange={(e) => set(k, e.target.value)} className={fieldClass} placeholder="–" />}
    </FormField>
  );

  const existing = (milestone?.screenshots ?? []).filter((s) => !removed.has(s.id));

  return (
    <form onSubmit={submit} noValidate className="space-y-4 p-4" data-testid="milestone-form">
      <FormField label="Tank *" error={errors.tank} hint="Známý tank dostane obrázek automaticky.">
        {(p) => (
          <div className="flex items-center gap-3">
            <GameImage kind="tank" name={draft.tank || "?"} size="sm" />
            <input {...p} list={ids.tanks} value={draft.tank} onChange={(e) => set("tank", e.target.value)} className={fieldClass} placeholder="např. Progetto 65" autoComplete="off" />
            <datalist id={ids.tanks}>
              {knownTanks.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </div>
        )}
      </FormField>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
        <FormField label="Mapa">
          {(p) => <input {...p} value={draft.map_name} onChange={(e) => set("map_name", e.target.value)} className={fieldClass} placeholder="např. Útesy" />}
        </FormField>
        <FormField label="Datum bitvy" error={errors.played_on}>
          {(p) => <input {...p} type="date" max={today} value={draft.played_on} onChange={(e) => set("played_on", e.target.value)} className={fieldClass} />}
        </FormField>
        {num("damage", "Poškození")}
        {num("assist", "Asistence")}
        {num("kills", "Zničení")}
        {num("base_xp", "Základní XP")}
      </div>
      <FormField label="Poznámka">
        {(p) => <textarea {...p} rows={3} value={draft.notes} onChange={(e) => set("notes", e.target.value)} className={fieldClass} placeholder="Co se stalo, proč je to památné…" />}
      </FormField>
      <label className="flex min-h-11 items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" checked={draft.favorite} onChange={(e) => set("favorite", e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
        <span aria-hidden="true">★</span> Legendární bitva (oblíbená)
      </label>

      <fieldset className="space-y-2 border-t border-line-subtle pt-4">
        <legend className="text-sm font-semibold text-ink">Screenshoty</legend>
        {existing.length ? (
          <ul className="space-y-2" aria-label="Uložené screenshoty">
            {existing.map((s, i) => (
              <li key={s.id} className="flex items-center gap-2">
                <span className="w-6 shrink-0 text-xs tabular-nums text-ink-muted">{i + 1}.</span>
                <input
                  aria-label={`Popisek screenshotu ${i + 1}`}
                  value={captions[s.id] ?? ""}
                  onChange={(e) => setCaptions((c) => ({ ...c, [s.id]: e.target.value }))}
                  className={cx(fieldClass, "min-w-0 flex-1")}
                  placeholder={s.original_name ?? "Popisek"}
                  maxLength={300}
                />
                <Button size="sm" variant="ghost" onClick={() => setRemoved((r) => new Set(r).add(s.id))} aria-label={`Odebrat screenshot ${i + 1}`}>
                  Odebrat
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        {pending.length ? (
          <ul className="space-y-2" aria-label="Screenshoty k nahrání">
            {pending.map((p) => (
              <li key={p.key} className="flex items-center gap-2">
                <span className="min-w-0 max-w-[40%] truncate text-xs text-ink-2">{p.file.name}</span>
                <input
                  aria-label={`Popisek: ${p.file.name}`}
                  value={p.caption}
                  onChange={(e) => setPending((list) => list.map((x) => (x.key === p.key ? { ...x, caption: e.target.value } : x)))}
                  className={cx(fieldClass, "min-w-0 flex-1")}
                  placeholder="Popisek (nepovinný)"
                  maxLength={300}
                />
                <Button size="sm" variant="ghost" onClick={() => setPending((list) => list.filter((x) => x.key !== p.key))} aria-label={`Nenahrávat ${p.file.name}`}>
                  ×
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
        <label htmlFor={ids.files} className="block text-xs text-ink-muted">
          Přidat obrázky (PNG, JPEG, WebP, max. 10 MB)
        </label>
        <input
          id={ids.files}
          type="file"
          multiple
          accept={SCREENSHOT_TYPES.join(",")}
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = "";
          }}
          className="block w-full text-sm text-ink-2 file:mr-3 file:min-h-10 file:rounded-[var(--radius-control)] file:border file:border-line file:bg-surface-2 file:px-3 file:text-sm file:text-ink"
        />
        {fileErrors.length ? (
          <ul role="alert" className="space-y-0.5 text-xs text-danger">
            {fileErrors.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        ) : null}
      </fieldset>

      {failure ? (
        <p role="alert" className="rounded-[var(--radius-control)] border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {failure}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-2 border-t border-line-subtle pt-4">
        <Button type="submit" variant="primary" busy={busy} busyLabel="Ukládám…">
          {saved ? "Uložit změny" : "Uložit milník"}
        </Button>
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          Zavřít
        </Button>
      </div>
    </form>
  );
}
