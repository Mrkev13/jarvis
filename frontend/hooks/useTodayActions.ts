"use client";

import { useCallback, useRef, useState } from "react";
import { apiFetch, jsonBody } from "@/lib/api";
import {
  classifyActionError,
  entityKind,
  fillTemplate,
  moduleAction,
  nextFocusId,
  parseRef,
  successMessage,
  type SnoozeOption,
  type TodayActionId,
  type TodayItem,
} from "@/lib/today";

export type TodayNotice = { tone: "success" | "warning" | "danger"; message: string; undo?: () => void };
/** Chyba řádku + co zopakovat („Zkusit znovu" volá run se stejnými argumenty). */
export type RowError = { message: string; action: TodayActionId; option?: SnoozeOption };

class ActionFailure extends Error {
  constructor(readonly status: number | null, readonly detail: unknown) {
    super("action failed");
  }
}

async function call(path: string, init: RequestInit): Promise<Record<string, unknown>> {
  let res: Response;
  try {
    res = await apiFetch(path, init);
  } catch {
    throw new ActionFailure(null, null); // síť
  }
  const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
  if (!res.ok) throw new ActionFailure(res.status, body?.detail ?? null);
  return body ?? {};
}

/** Potvrzení pending akce (stejné jako u AI / Rychlého přidání); ok:false = zastaralé nebo selhání. */
async function confirmPending(actionId: string): Promise<Record<string, unknown>> {
  const body = await call("/actions/confirm", jsonBody("POST", { action_id: actionId }));
  if (body.ok) return body;
  const processed = body.error === "action_already_processed" || body.error === "action_not_found_or_expired";
  const staleDetail = typeof body.detail === "string" && /změnil|zmizel/.test(body.detail);
  throw new ActionFailure(processed || staleDetail ? 409 : 500, processed ? "Akce už byla zpracována." : body.detail ?? null);
}

/**
 * Akce z režimu Dnes (Roadmap 4H). Jedna akce najednou: mutace (připomínky přímo, úkoly přes pending akci
 * + /actions/confirm) → JEDNO obnovení GET /today. Zastaralý stav = hláška + obnovení; jiná chyba = řádek
 * zůstane s „Zkusit znovu" (u úkolu se znovu potvrdí TATÁŽ pending akce, žádná druhá). Vrácení jen tam,
 * kde ho backend podporuje (dokončení úkolu).
 */
export function useTodayActions(reload: () => Promise<void>) {
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, RowError>>({});
  const [notice, setNotice] = useState<TodayNotice | null>(null);
  const pendingIds = useRef<Record<string, string>>({});
  const busyRef = useRef(false);

  const focusAfter = useCallback((targetId: string | null) => {
    window.requestAnimationFrame(() => {
      const el =
        (targetId && document.querySelector<HTMLElement>(`[data-item="${CSS.escape(targetId)}"] [data-action-primary]`)) ||
        document.querySelector<HTMLElement>("[data-today-notice]");
      el?.focus();
    });
  }, []);

  const finish = useCallback(
    async (next: TodayNotice, focusId: string | null) => {
      setNotice(next);
      await reload();
      focusAfter(focusId);
    },
    [reload, focusAfter],
  );

  const undoAction = useCallback(
    async (originalId: string, title: string) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusyKey("undo");
      try {
        const proposed = await call("/actions/undo", jsonBody("POST", { action_id: originalId }));
        if (!proposed.ok) throw new ActionFailure(409, proposed.detail ?? "Tuhle změnu už nejde vrátit.");
        const pendingId = String((proposed.pending_action as { id?: unknown } | undefined)?.id ?? "");
        await confirmPending(pendingId);
        await finish({ tone: "success", message: `Vráceno: „${title}“ je znovu otevřený.` }, null);
      } catch (error) {
        const failure = error instanceof ActionFailure ? error : new ActionFailure(null, null);
        const text = typeof failure.detail === "string" ? failure.detail : "Vrácení se nepodařilo.";
        setNotice({ tone: "danger", message: text });
        if (failure.status === 409) await reload();
      } finally {
        busyRef.current = false;
        setBusyKey(null);
      }
    },
    [finish, reload],
  );

  const run = useCallback(
    async (item: TodayItem, action: TodayActionId, option?: SnoozeOption) => {
      if (busyRef.current || action === "record_result") return;
      const ref = parseRef(item.id);
      const kind = entityKind(item);
      if (!ref || !kind) return;
      // další akční řádek ve stejném seznamu (pro fokus po obnovení)
      const row = document.querySelector(`[data-item="${CSS.escape(item.id)}"]`);
      const siblings = row?.closest("ul")
        ? [...row.closest("ul")!.querySelectorAll<HTMLElement>("[data-item][data-actionable]")].map((el) => el.dataset.item ?? "")
        : [];
      const focusId = nextFocusId(siblings, item.id);
      busyRef.current = true;
      setBusyKey(`${item.id}:${action}`);
      setNotice(null); // stará hláška nepatří k nové akci
      setRowErrors((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => id !== item.id)));
      try {
        let undo: (() => void) | undefined;
        const declared = moduleAction(item, action);
        if (declared) {
          // MRK-21: akce modulu z manifestu (MODULE_UI.<id>.todayActions) – endpoint modulu, žádná větev na typ
          await call(fillTemplate(declared.path, { id: ref.id }), jsonBody("POST", declared.body ?? {}));
        } else if (kind === "reminder" && action === "complete") {
          await call(`/reminders/${ref.id}/done?source=today`, { method: "POST" });
        } else if (kind === "reminder" && action === "snooze" && option) {
          const body = option.minutes ? { minutes: option.minutes } : { until_local: option.until_local };
          await call(`/reminders/${ref.id}/snooze?source=today`, jsonBody("POST", body));
        } else if (kind === "assignment" && action === "complete") {
          let actionId = pendingIds.current[item.id];
          if (!actionId) {
            const prepared = await call("/today/actions/prepare", jsonBody("POST", { action: "complete", ref: `assignment:${ref.id}` }));
            actionId = String((prepared.pending_action as { id?: unknown } | undefined)?.id ?? "");
            if (!actionId) throw new ActionFailure(500, null);
            pendingIds.current[item.id] = actionId;
          }
          const confirmed = await confirmPending(actionId);
          delete pendingIds.current[item.id];
          const result = confirmed.result as { undo_available?: boolean } | undefined;
          if (result?.undo_available) {
            const original = actionId;
            undo = () => void undoAction(original, item.title);
          }
        } else {
          return;
        }
        await finish({ tone: "success", message: successMessage(item, action, option?.label), undo }, focusId);
      } catch (error) {
        const failure = error instanceof ActionFailure ? error : new ActionFailure(null, null);
        const { stale, message } = classifyActionError(failure.status, failure.detail);
        if (stale) {
          delete pendingIds.current[item.id];
          await finish({ tone: "warning", message }, focusId);
        } else {
          setRowErrors((prev) => ({ ...prev, [item.id]: { message, action, option } }));
        }
      } finally {
        busyRef.current = false;
        setBusyKey(null);
      }
    },
    [finish, undoAction],
  );

  return { busyKey, rowErrors, notice, dismissNotice: () => setNotice(null), run };
}
