import { Button, Card, Progress, StatusBadge } from "@/components/ui";
import { formatDateTime, formatPercent } from "@/lib/format";
import { statusMeta, type MffCharacterItem } from "@/lib/mff";
import { priorityTone } from "@/lib/ui";

/** Jedna sledovaná postava: tier, stav, priorita, role, výbava a průběh buildu. */
export function CharacterCard({
  character: c,
  index,
  onDelete,
}: {
  character: MffCharacterItem;
  index: number;
  onDelete: (c: MffCharacterItem) => void;
}) {
  const bc = Math.max(0, Math.min(100, Number(c.build_completeness) || 0));
  const tierStr = (c.tier || "").trim() || "–";
  const uruTotal = Number(c.uru_slots_total) || 0;
  const uruFilled = Number(c.uru_slots_filled) || 0;
  const ob = Number(c.odin_blessings_count) || 0;
  const teamStr = c.team_supports || c.team || "";
  const roles = Array.isArray(c.roles) && c.roles.length > 0 ? c.roles : c.role ? [c.role] : [];
  const status = statusMeta(c.status);
  const prio = priorityTone(c.priority);
  const complete = bc >= 100;
  const builtStatus = (c.status || "").toLowerCase() === "built";
  const titleId = `mff-char-${c.id}`;

  const details: Array<[string, string]> = [];
  if (c.ctp) details.push(["CTP", c.ctp]);
  if (c.artifact) details.push(["Artifact", c.artifact]);
  if (c.iso8_set) details.push(["ISO-8", c.iso8_set]);
  if (teamStr) details.push(["Tým", teamStr]);
  if (uruTotal > 0) details.push(["Uru", `${uruFilled} / ${uruTotal}`]);
  else if (c.uru_state) details.push(["Uru", c.uru_state]);
  if (ob > 0) details.push(["Odin's Blessings", String(ob)]);

  return (
    <Card as="li" index={index} aria-labelledby={titleId} data-search-target={`character-${c.id}`} className="flex min-w-0 flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge className="font-mono font-semibold text-ink">{tierStr}</StatusBadge>
            {c.level != null ? <span className="text-xs tabular-nums text-ink-muted">Lv. {c.level}</span> : null}
          </div>
          <h3 id={titleId} className="mt-1.5 break-words text-base font-semibold text-ink md:text-lg">
            {c.name}
          </h3>
          {c.uniform ? (
            <p className="mt-0.5 break-words text-xs text-ink-muted">
              Uniform: <span className="text-ink-2">{c.uniform}</span>
            </p>
          ) : null}
        </div>
        <Button size="sm" variant="ghost" onClick={() => onDelete(c)} aria-label={`Smazat postavu ${c.name}`}>
          Smazat
        </Button>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <StatusBadge tone={status.tone} dot={status.tone !== "neutral"}>
          {status.label}
        </StatusBadge>
        <StatusBadge tone={prio.tone}>Priorita: {prio.label}</StatusBadge>
        {complete ? <StatusBadge tone="success">Kompletní build</StatusBadge> : null}
      </div>

      {roles.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5" aria-label="Role">
          {roles.map((r, i) => (
            <li key={`${r}-${i}`}>
              <StatusBadge>{String(r)}</StatusBadge>
            </li>
          ))}
        </ul>
      ) : null}

      {details.length > 0 ? (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-2">
          {details.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="inline text-xs text-ink-muted">{label}: </dt>
              <dd className="inline break-words text-ink-2">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <div>
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="text-ink-muted">Kompletnost buildu</span>
          <span className="font-semibold tabular-nums text-ink">{formatPercent(bc)}</span>
        </div>
        <Progress value={bc} label={`Kompletnost buildu ${c.name}`} />
        {complete && !builtStatus ? (
          <p className="mt-1 text-xs text-success">Build je kompletní – doporučený stav Postaveno.</p>
        ) : null}
      </div>

      {c.notes ? (
        <div className="border-t border-line-subtle pt-3">
          <h4 className="mb-1 text-xs font-medium text-ink-muted">Poznámky k buildu</h4>
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink-2">{c.notes}</p>
        </div>
      ) : null}

      {c.updated_at ? (
        <p className="mt-auto text-xs text-ink-faint">Upraveno {formatDateTime(c.updated_at)}</p>
      ) : null}
    </Card>
  );
}
