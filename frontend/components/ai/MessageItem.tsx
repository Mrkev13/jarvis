import { memo } from "react";
import PlannerCardRenderer, { type PlannerCard } from "@/components/PlannerCards";
import { messageVariant, stripStatusSymbol, type ChatMessage } from "@/lib/aiChat";
import { formatTime } from "@/lib/format";
import { plannerSpeechSummary, type SpeechLocale, type SpeechPlannerCard } from "@/lib/speech";
import { cx } from "@/lib/ui";
import { Markdown } from "./Markdown";

export type MessageTts = {
  enabled: boolean;
  activeKey: string | null;
  locale: SpeechLocale;
  play: (key: string, text: string, locale: SpeechLocale) => void;
  stop: () => void;
};

function SpeakButton({ ttsKey, text, label, tts }: { ttsKey: string; text: string; label: string; tts: MessageTts }) {
  const active = tts.activeKey === ttsKey;
  return (
    <button
      type="button"
      aria-label={active ? `Zastavit čtení: ${label}` : `Přečíst nahlas: ${label}`}
      aria-pressed={active}
      onClick={() => (active ? tts.stop() : tts.play(ttsKey, text, tts.locale))}
      className={cx(
        "grid h-9 w-9 shrink-0 place-items-center rounded-lg text-sm transition-colors pointer-coarse:h-11 pointer-coarse:w-11",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
        active ? "bg-danger/15 text-danger" : "text-ink-muted hover:bg-hover hover:text-ink",
      )}
    >
      <span aria-hidden="true">{active ? "■" : "🔊"}</span>
    </button>
  );
}

const STATUS_STYLE = {
  success: { icon: "✓", box: "border-success/30 bg-success/[0.06]", iconCls: "text-success", label: "Hotovo" },
  warning: { icon: "!", box: "border-warning/35 bg-warning/[0.06]", iconCls: "text-warning", label: "Upozornění" },
  error: { icon: "✕", box: "border-danger/35 bg-danger/[0.06]", iconCls: "text-danger", label: "Chyba" },
} as const;

/**
 * Jedna zpráva konverzace. Uživatel: střídmá plocha vpravo. Asistent: hlavní obsah bez bubliny
 * (Markdown + případně karta Planneru). Stavové zprávy (✅ / ⚠️ / ❌, výsledky akcí a chyby) kompaktně.
 */
export const MessageItem = memo(function MessageItem({
  message: m,
  showAuthor,
  tts,
}: {
  message: ChatMessage;
  /** Popisek „Standa AI" jen u první zprávy asistenta ve skupině (žádné opakované avatary). */
  showAuthor: boolean;
  tts: MessageTts | null;
}) {
  if (m.role === "user") {
    return (
      <li className="flex justify-end">
        <div className="max-w-[85%] rounded-card rounded-br-md border border-line bg-surface-2 px-4 py-2.5 text-[15px] leading-7 text-ink sm:max-w-[75%]">
          <span className="sr-only">Ty: </span>
          <p className="whitespace-pre-wrap break-words">{m.content}</p>
        </div>
      </li>
    );
  }

  const variant = messageVariant(m);
  if (variant !== "normal" && !m.plannerCard) {
    const s = STATUS_STYLE[variant];
    return (
      <li>
        <div className={cx("flex gap-3 rounded-[var(--radius-control)] border px-3 py-2.5 text-sm", s.box)}>
          <span aria-hidden="true" className={cx("mt-0.5 font-semibold", s.iconCls)}>
            {s.icon}
          </span>
          <div className="min-w-0 flex-1 break-words">
            <span className="sr-only">{s.label}: </span>
            {(() => {
              // „Hlavička\n\nřádek\nřádek" → hlavička + detaily na jednom řádku
              const [head, ...rest] = stripStatusSymbol(m.content).split(/\n\s*\n/);
              const details = rest.join("\n").split("\n").map((l) => l.trim()).filter(Boolean);
              return (
                <>
                  <p className="whitespace-pre-wrap font-medium text-ink">{head}</p>
                  {details.length ? <p className="mt-0.5 text-ink-muted">{details.join(" · ")}</p> : null}
                </>
              );
            })()}
          </div>
        </div>
      </li>
    );
  }

  return (
    <li className="min-w-0">
      {showAuthor ? (
        <div className="mb-1.5 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.16em] text-ink-faint">
          <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-accent-2 shadow-[0_0_8px_rgb(167_139_250/0.7)]" />
          Standa AI
          <time className="normal-case tracking-normal" dateTime={new Date(m.createdAt).toISOString()}>
            {formatTime(new Date(m.createdAt).toISOString())}
          </time>
        </div>
      ) : (
        <span className="sr-only">Standa AI: </span>
      )}
      <div className="space-y-3">
        {m.content ? (
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <Markdown content={m.content} />
            </div>
            {tts?.enabled ? <SpeakButton ttsKey={`text-${m.id}`} text={m.content} label="odpověď" tts={tts} /> : null}
          </div>
        ) : null}
        {m.plannerCard ? (
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <PlannerCardRenderer card={m.plannerCard as PlannerCard} compact />
            </div>
            {tts?.enabled ? (
              <SpeakButton
                ttsKey={`plan-${m.id}`}
                text={plannerSpeechSummary(m.plannerCard as unknown as SpeechPlannerCard)}
                label="plán"
                tts={tts}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </li>
  );
});

/** Indikátor odpovídání (při omezeném pohybu bez poskakování – animate-* vypíná motion.css). */
export function ThinkingIndicator() {
  return (
    <li role="status" className="flex items-center gap-2 text-sm text-ink-muted">
      <span aria-hidden="true" className="flex gap-1">
        {[0, 120, 240].map((d) => (
          <span key={d} className="h-1.5 w-1.5 animate-bounce rounded-full bg-accent-2" style={{ animationDelay: `${d}ms` }} />
        ))}
      </span>
      Standa AI přemýšlí…
    </li>
  );
}
