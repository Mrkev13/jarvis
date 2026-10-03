"use client";

import { useMemo, useState } from "react";
import { Button, Card, CardHeader, FilterChips, FormField, fieldClass, Progress } from "@/components/ui";
import { formatPercent } from "@/lib/format";
import {
  characterPayload,
  emptyCharacterForm,
  formBuildCompleteness,
  PRIORITY_OPTIONS,
  ROLE_OPTIONS,
  STATUS_OPTIONS,
  statusMeta,
  TIER_OPTIONS,
  validateCharacterForm,
  type CharacterForm as FormState,
  type CharacterPayload,
  type CharacterFormErrors,
  type RoleOption,
} from "@/lib/mff";
import { priorityTone } from "@/lib/ui";

const ROLE_CHIPS = ROLE_OPTIONS.map((r) => ({ value: r, label: r }));

/**
 * Formulář nové postavy. Stav drží sám – po zavření (odmontování) začíná znovu s výchozími hodnotami,
 * stejně jako dřívější resetForm při otevření/zavření.
 */
export function CharacterForm({
  id,
  submitting,
  disabled,
  onSubmit,
  onCancel,
}: {
  id: string;
  submitting: boolean;
  disabled: boolean;
  onSubmit: (payload: CharacterPayload) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<FormState>(() => emptyCharacterForm());
  const [errors, setErrors] = useState<CharacterFormErrors>({});
  const liveBuild = useMemo(() => formBuildCompleteness(form), [form]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function toggleRole(r: string) {
    const role = r as RoleOption;
    setForm((f) => ({ ...f, roles: f.roles.includes(role) ? f.roles.filter((x) => x !== role) : [...f.roles, role] }));
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const errs = validateCharacterForm(form);
    setErrors(errs);
    if (Object.keys(errs).length > 0) return;
    onSubmit(characterPayload(form));
  }

  const text = (key: "name" | "uniform" | "ctp" | "artifact" | "teamSupports" | "iso8Set", label: string, placeholder: string, className?: string) => (
    <FormField label={label} className={className} error={key === "name" ? errors.name : undefined}>
      {(p) => (
        <input
          {...p}
          type="text"
          value={form[key]}
          onChange={(e) => set(key, e.target.value)}
          placeholder={placeholder}
          className={fieldClass}
        />
      )}
    </FormField>
  );

  const num = (key: "level" | "uruSlotsFilled" | "uruSlotsTotal" | "odinBlessings", label: string, min: number, max?: number) => (
    <FormField label={label} error={errors[key]}>
      {(p) => (
        <input
          {...p}
          type="number"
          inputMode="numeric"
          min={min}
          max={max}
          value={form[key]}
          onChange={(e) => set(key, e.target.value)}
          className={fieldClass}
        />
      )}
    </FormField>
  );

  return (
    <Card as="section" id={id} aria-labelledby={`${id}-title`}>
      <CardHeader title={<span id={`${id}-title`}>Nová postava</span>} />
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {text("name", "Jméno (povinné)", "např. Black Bolt")}
          <FormField label="Tier">
            {(p) => (
              <select {...p} value={form.tier} onChange={(e) => set("tier", e.target.value)} className={fieldClass}>
                {TIER_OPTIONS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            )}
          </FormField>
          {num("level", "Level", 1, 80)}
          {text("uniform", "Uniform", "např. Hellfire Club")}
          {text("ctp", "CTP", "např. Rage / Regeneration / -")}
          {text("artifact", "Artifact", "např. Arachne 6*")}
          <div className="md:col-span-2 lg:col-span-3">
            <FilterChips label="Role" options={ROLE_CHIPS} selected={form.roles} onToggle={toggleRole} />
          </div>
          {text("teamSupports", "Tým / podpora", "např. White Fox + Shuri", "md:col-span-2 lg:col-span-3")}
          {num("uruSlotsFilled", "Uru sloty – zaplněno", 0)}
          {num("uruSlotsTotal", "Uru sloty – celkem", 0)}
          {num("odinBlessings", "Odin's Blessings", 0)}
          {text("iso8Set", "ISO-8 set", "např. Power of Angry Hulk")}
          <FormField label="Priorita">
            {(p) => (
              <select {...p} value={form.priority} onChange={(e) => set("priority", e.target.value)} className={fieldClass}>
                {PRIORITY_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {priorityTone(v).label}
                  </option>
                ))}
              </select>
            )}
          </FormField>
          <FormField label="Stav">
            {(p) => (
              <select {...p} value={form.status} onChange={(e) => set("status", e.target.value)} className={fieldClass}>
                {STATUS_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {statusMeta(v).label}
                  </option>
                ))}
              </select>
            )}
          </FormField>
          <div className="space-y-1.5 md:col-span-2 lg:col-span-3">
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="font-medium text-ink-2">Kompletnost buildu (počítá se automaticky)</span>
              <span className="font-semibold tabular-nums text-ink">{formatPercent(liveBuild)}</span>
            </div>
            <Progress value={liveBuild} label="Kompletnost buildu nové postavy" />
            <p className="text-xs text-ink-muted">
              Sledovaných 8 složek: T4, Level 80, Uniform, CTP, Artifact, plné Uru sloty, ISO-8 set, tým / podpora.
            </p>
          </div>
          <FormField label="Poznámky" hint="Nepovinné" className="md:col-span-2 lg:col-span-3">
            {(p) => (
              <textarea
                {...p}
                rows={2}
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
                placeholder="Poznámky k buildu…"
                className={`${fieldClass} resize-none`}
              />
            )}
          </FormField>
        </div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={onCancel}>
            Storno
          </Button>
          <Button type="submit" variant="primary" busy={submitting} busyLabel="Ukládám…" disabled={disabled}>
            Uložit postavu
          </Button>
        </div>
      </form>
    </Card>
  );
}
