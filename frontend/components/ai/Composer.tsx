"use client";

import { useId, useLayoutEffect, useState } from "react";
import { Button, ErrorState, fieldClass } from "@/components/ui";
import type { AiVoice } from "@/hooks/useAiVoice";
import type { ChatFailure } from "@/lib/aiChat";
import { SUPPORTED_LOCALES, type SpeechLocale } from "@/lib/speech";
import { cx } from "@/lib/ui";

const MAX_TEXTAREA_PX = 200;

/**
 * Pole pro zprávu (Roadmap 4C): popisek, Enter = odeslat, Shift+Enter = nový řádek, výška roste s textem
 * do rozumné meze. Hlas (diktování, předčítání, jazyk) beze změny chování – nastavení je pod „Hlas".
 */
export function Composer({
  value,
  onChange,
  onSend,
  sending,
  disabled,
  failure,
  onRetry,
  onDismissFailure,
  voice,
  textareaRef,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  sending: boolean;
  disabled: boolean;
  failure: (ChatFailure & { prompt: string }) | null;
  onRetry: () => void;
  onDismissFailure: () => void;
  voice: AiVoice;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const ids = { input: useId(), hint: useId(), settings: useId(), locale: useId() };
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { stt, tts } = voice;
  const canSend = !sending && !disabled && value.trim().length > 0;

  // výška podle obsahu (1 řádek → max. ~8 řádků)
  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    const h = Math.min(el.scrollHeight, MAX_TEXTAREA_PX);
    el.style.height = `${h}px`;
    el.style.overflowY = el.scrollHeight > MAX_TEXTAREA_PX ? "auto" : "hidden";
  }, [value, textareaRef]);

  const voiceStatus =
    stt.status === "listening" ? "Poslouchám…" : stt.status === "processing" ? "Zpracovávám řeč…" : stt.status === "error" ? stt.error : null;

  return (
    <div className="border-t border-line bg-app/85 backdrop-blur safe-bottom">
      <div className="mx-auto w-full max-w-4xl space-y-2 px-4 py-3 md:px-6">
        {failure ? (
          <div className="flex items-start gap-1">
            <ErrorState
              message={
                <>
                  <span className="font-medium">{failure.notice}</span>
                  {failure.kind === "daily_limit" ? null : <span className="text-ink-muted"> Zprávu můžeš odeslat znovu.</span>}
                </>
              }
              onRetry={failure.kind === "daily_limit" ? undefined : onRetry}
              className="flex-1 py-2"
            />
            <Button size="sm" variant="ghost" onClick={onDismissFailure} aria-label="Skrýt upozornění">
              ✕
            </Button>
          </div>
        ) : null}

        {voiceStatus || (stt.listening && (stt.transcript || stt.interim)) ? (
          <div
            role="status"
            className={cx(
              "flex items-start justify-between gap-3 rounded-[var(--radius-control)] border px-3 py-2 text-sm",
              stt.status === "error" ? "border-danger/40 bg-danger/[0.06]" : "border-accent/30 bg-accent/[0.05]",
            )}
          >
            <div className="min-w-0">
              {voiceStatus ? <div className="font-medium text-ink">{voiceStatus}</div> : null}
              {stt.status === "listening" && (stt.transcript || stt.interim) ? (
                <div className="mt-0.5 break-words text-ink-2">
                  {stt.transcript} <span className="italic text-ink-muted">{stt.interim || "…"}</span>
                </div>
              ) : null}
            </div>
            {stt.listening || stt.status === "error" ? (
              <Button size="sm" variant="ghost" onClick={() => stt.stop()}>
                Zastavit
              </Button>
            ) : null}
          </div>
        ) : null}

        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSend) onSend();
          }}
        >
          <div className="min-w-0 flex-1">
            <label htmlFor={ids.input} className="sr-only">
              Zpráva pro Standa AI
            </label>
            <textarea
              id={ids.input}
              ref={textareaRef}
              value={value}
              rows={1}
              aria-describedby={ids.hint}
              placeholder="Napiš, co potřebuješ…"
              onChange={(e) => onChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (canSend) onSend();
                }
              }}
              className={cx(fieldClass, "block min-h-11 resize-none py-2.5 text-[15px] leading-6")}
            />
          </div>
          <button
            type="button"
            onClick={stt.toggle}
            disabled={!stt.supported || sending}
            aria-pressed={stt.listening}
            aria-label={stt.listening ? "Zastavit diktování" : "Diktovat zprávu (Ctrl+Shift+M)"}
            title={stt.supported ? undefined : "Hlasové zadávání není v tomto prohlížeči podporováno."}
            className={cx(
              "grid h-11 w-11 shrink-0 place-items-center rounded-[var(--radius-control)] border text-base transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 disabled:cursor-not-allowed disabled:opacity-40",
              stt.listening ? "border-danger/50 bg-danger/15 text-danger" : "border-line bg-surface-2 text-ink-2 hover:bg-hover",
            )}
          >
            <span aria-hidden="true">🎤</span>
          </button>
          <Button type="submit" variant="primary" className="min-h-11 shrink-0" disabled={!canSend} busy={sending} busyLabel="Odesílám…">
            Odeslat
          </Button>
        </form>

        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-ink-muted">
          <span id={ids.hint}>Enter odešle · Shift+Enter nový řádek</span>
          <button
            type="button"
            aria-expanded={settingsOpen}
            aria-controls={ids.settings}
            onClick={() => setSettingsOpen((o) => !o)}
            className="inline-flex min-h-9 items-center gap-1 rounded-md px-1.5 text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 pointer-coarse:min-h-11"
          >
            Hlas <span aria-hidden="true">{settingsOpen ? "▴" : "▾"}</span>
          </button>
        </div>

        {settingsOpen ? (
          <fieldset id={ids.settings} className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-[var(--radius-control)] border border-line-subtle bg-surface px-3 py-2 text-sm text-ink-2">
            <legend className="sr-only">Nastavení hlasu</legend>
            <label className="inline-flex min-h-9 items-center gap-2">
              <input type="checkbox" checked={stt.autoSend} onChange={(e) => stt.setAutoSend(e.target.checked)} className="h-4 w-4 accent-[var(--color-accent)]" />
              Odeslat po diktování
            </label>
            <label className="inline-flex min-h-9 items-center gap-2">
              <input
                type="checkbox"
                checked={tts.enabled}
                disabled={!tts.supported}
                onChange={(e) => tts.setEnabled(e.target.checked)}
                className="h-4 w-4 accent-[var(--color-accent)] disabled:opacity-50"
              />
              Předčítat odpovědi
            </label>
            <span className="inline-flex items-center gap-2">
              <label htmlFor={ids.locale}>Jazyk hlasu</label>
              <select
                id={ids.locale}
                value={stt.locale}
                onChange={(e) => stt.setLocale(e.target.value as SpeechLocale)}
                className={cx(fieldClass, "min-h-9 w-auto py-1")}
              >
                {SUPPORTED_LOCALES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </span>
            {!stt.supported ? <span className="text-xs text-ink-muted">Diktování tento prohlížeč neumí (zkus Chrome nebo Edge).</span> : null}
          </fieldset>
        ) : null}
      </div>
    </div>
  );
}
