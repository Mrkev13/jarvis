"use client";

import { useEffect, useState } from "react";
import { Button, Card, EmptyState, FormField, fieldClass, StatusBadge } from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import {
  creditsLabel,
  subjectDraftFrom,
  subjectPatch,
  visibleSubjects,
  type SchoolSubject,
  type SubjectDraft,
} from "@/lib/school";
import { cx } from "@/lib/ui";

/**
 * MRK-75: předměty – úprava a archivace (PATCH /school/subject/{id}). Archivace jen skryje předmět z nabídek;
 * úkoly, zkoušky, kurzy a materiály zůstávají a předmět jde kdykoli obnovit.
 */
export function SubjectList({ subjects, onChanged }: { subjects: SchoolSubject[]; onChanged: () => Promise<void> }) {
  const [showArchived, setShowArchived] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState<SubjectDraft>({ name: "", code: "", semester: "", credits: "" });
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<{ id: number; text: string } | null>(null);
  const archivedCount = subjects.filter((s) => !s.active).length;

  // odkaz z vyhledávání na archivovaný předmět (/school?subject=12) → ukaž archiv, ať se dá zvýraznit
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("subject"));
    if (id && subjects.some((s) => s.id === id && !s.active)) queueMicrotask(() => setShowArchived(true));
  }, [subjects]);

  async function save(subject: SchoolSubject, patch: Partial<SchoolSubject>) {
    setBusy(subject.id);
    setError(null);
    try {
      if (Object.keys(patch).length > 0) {
        await apiJson(`/school/subject/${subject.id}`, jsonBody("PATCH", patch));
        await onChanged();
      }
      setEditing(null);
    } catch (e) {
      setError({ id: subject.id, text: errorMessage(e, "Předmět se nepodařilo uložit.") });
    } finally {
      setBusy(null);
    }
  }

  function startEdit(subject: SchoolSubject) {
    setError(null);
    setDraft(subjectDraftFrom(subject));
    setEditing(subject.id);
  }

  function submitEdit(e: React.FormEvent, subject: SchoolSubject) {
    e.preventDefault();
    const patch = subjectPatch(subject, draft);
    if (patch === null) {
      setError({ id: subject.id, text: "Vyplň název a kredity 0–99." });
      return;
    }
    void save(subject, patch);
  }

  const list = visibleSubjects(subjects, showArchived);
  return (
    <div className="space-y-3">
      {archivedCount > 0 ? (
        <label className="flex min-h-10 w-fit cursor-pointer select-none items-center gap-2 text-sm text-ink-2">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="h-4 w-4 accent-[var(--color-accent)]"
          />
          Zobrazit archivované ({archivedCount})
        </label>
      ) : null}

      {list.length === 0 ? (
        <EmptyState compact>
          {subjects.length === 0 ? "Zatím žádné předměty." : "Všechny předměty jsou archivované."}
        </EmptyState>
      ) : (
        <ul aria-label="Předměty" className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
          {list.map((s) => (
            <Card
              as="li"
              inset
              key={s.id}
              data-search-target={`subject-${s.id}`}
              className={cx("min-w-0", !s.active && editing !== s.id && "opacity-70")}
            >
              {editing === s.id ? (
                <form onSubmit={(e) => submitEdit(e, s)} className="space-y-3" aria-label={`Upravit předmět ${s.name}`}>
                  <FormField label="Název *">
                    {(p) => (
                      <input {...p} type="text" maxLength={150} value={draft.name} className={fieldClass}
                        onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
                    )}
                  </FormField>
                  <div className="grid grid-cols-2 gap-2">
                    <FormField label="Kód">
                      {(p) => (
                        <input {...p} type="text" maxLength={50} value={draft.code} className={fieldClass}
                          onChange={(e) => setDraft((d) => ({ ...d, code: e.target.value }))} />
                      )}
                    </FormField>
                    <FormField label="Kredity">
                      {(p) => (
                        <input {...p} type="number" min="0" max="99" inputMode="numeric" value={draft.credits}
                          className={fieldClass} onChange={(e) => setDraft((d) => ({ ...d, credits: e.target.value }))} />
                      )}
                    </FormField>
                  </div>
                  <FormField label="Semestr">
                    {(p) => (
                      <input {...p} type="text" maxLength={50} value={draft.semester} className={fieldClass}
                        onChange={(e) => setDraft((d) => ({ ...d, semester: e.target.value }))} />
                    )}
                  </FormField>
                  {error?.id === s.id ? <p role="alert" className="text-sm text-danger">{error.text}</p> : null}
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" size="sm" variant="primary" busy={busy === s.id} busyLabel="Ukládám…">
                      Uložit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                      Zrušit
                    </Button>
                  </div>
                </form>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <h3 className="min-w-0 break-words font-medium text-ink">{s.name}</h3>
                    {s.code ? <span className="font-mono text-xs text-ink-muted">{s.code}</span> : null}
                    {!s.active ? <StatusBadge tone="neutral">Archivovaný</StatusBadge> : null}
                  </div>
                  {s.semester || s.credits > 0 ? (
                    <p className="mt-0.5 text-sm text-ink-muted">
                      {[s.semester, s.credits > 0 ? creditsLabel(s.credits) : ""].filter(Boolean).join(" · ")}
                    </p>
                  ) : null}
                  {error?.id === s.id ? <p role="alert" className="mt-1 text-sm text-danger">{error.text}</p> : null}
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => startEdit(s)}>
                      Upravit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      busy={busy === s.id}
                      busyLabel="Ukládám…"
                      disabled={busy !== null && busy !== s.id}
                      onClick={() => void save(s, { active: !s.active })}
                    >
                      {s.active ? "Archivovat" : "Obnovit"}
                    </Button>
                  </div>
                </>
              )}
            </Card>
          ))}
        </ul>
      )}
    </div>
  );
}
