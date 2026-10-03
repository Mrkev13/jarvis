"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Button, EmptyState, ErrorState, StatusPulse } from "@/components/ui";
import { SearchIcon } from "./SearchIcon";
import { useModal } from "@/components/ui/useModal";
import { useGlobalSearch } from "@/hooks/useGlobalSearch";
import { flatten, moveSelection, parseRecent, pushRecent, RECENT_KEY, type SearchResult } from "@/lib/search";
import { MAIN_CONTENT_ID } from "@/lib/shell";
import { cx } from "@/lib/ui";

function readRecent(): SearchResult[] {
  try {
    return parseRecent(window.localStorage.getItem(RECENT_KEY));
  } catch {
    return [];
  }
}

function saveRecent(list: SearchResult[]) {
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch {
    /* soukromé okno / zakázané úložiště – nedávné se jen neuloží */
  }
}

/**
 * Paleta příkazů (Ctrl+K): vyhledávací pole (combobox) + výsledky ve skupinách (listbox). Šipky vybírají,
 * Enter otevře, Esc zavře a vrátí fokus. Jen navigace – paleta nic neukládá ani neprovádí (to je Quick Add).
 * Desktop: kompaktní panel nahoře; mobil: celá obrazovka s polem nahoře.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return <PaletteDialog onClose={onClose} />;
}

function PaletteDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const ids = { title: useId(), input: useId(), list: useId(), status: useId() };
  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [recent, setRecent] = useState<SearchResult[]>([]);
  const [navigated, setNavigated] = useState(false);

  useEffect(() => {
    queueMicrotask(() => setRecent(readRecent()));
  }, []);

  useModal({ open: true, panelRef, initialFocus: () => inputRef.current, onClose, restoreFocus: !navigated });

  const search = useGlobalSearch(query, { enabled: true, recent });
  const options = useMemo(() => flatten(search.groups), [search.groups]);
  const activeIndex = options.length ? Math.min(active, options.length - 1) : -1;
  const activeOption = activeIndex >= 0 ? options[activeIndex] : null;
  const optionId = (r: SearchResult) => `${ids.list}-${r.id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

  // vybraný řádek vždy viditelný
  useEffect(() => {
    if (!activeOption) return;
    document.getElementById(optionId(activeOption))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeOption?.id]);

  function openResult(r: SearchResult) {
    const next = pushRecent(recent, r);
    saveRecent(next);
    setNavigated(true);
    onClose();
    router.push(r.href);
    // stránka bez zvýrazněného záznamu: fokus na obsah (záznam si fokus vezme SearchHighlighter)
    if (!r.href.includes("?")) window.setTimeout(() => document.getElementById(MAIN_CONTENT_ID)?.focus({ preventScroll: true }), 120);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive(moveSelection(activeIndex, options.length, e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeOption) openResult(activeOption);
    } else if (e.key === "Home" && e.ctrlKey) {
      setActive(0);
    }
  }

  const resultCount = query.trim() ? options.length : 0;
  const statusText = search.searching
    ? "Hledám…"
    : search.error
      ? "Hledání v datech selhalo."
      : search.empty
        ? "Nic nenalezeno."
        : query.trim()
          ? `${resultCount} ${resultCount === 1 ? "výsledek" : resultCount >= 2 && resultCount <= 4 ? "výsledky" : "výsledků"}`
          : "";

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm sm:px-4"
      onMouseDown={(e) => {
        if (e.target !== e.currentTarget) return;
        e.preventDefault();
        onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={ids.title}
        className={cx(
          "motion-palette relative flex h-dvh w-full flex-col overflow-hidden bg-elevated focus:outline-none",
          "sm:mx-auto sm:mt-[12vh] sm:h-auto sm:max-h-[min(36rem,76vh)] sm:max-w-xl sm:rounded-card sm:border sm:border-line sm:shadow-[var(--shadow-elevated)]",
        )}
      >
        <div aria-hidden="true" className="h-px bg-gradient-to-r from-transparent via-accent/60 to-transparent" />
        <h2 id={ids.title} className="sr-only">
          Hledat v Standa Hubu
        </h2>
        <div className="flex items-center gap-2 border-b border-line px-3 py-2 sm:px-4">
          <SearchIcon className="h-5 w-5 shrink-0 text-ink-muted" />
          <label htmlFor={ids.input} className="sr-only">
            Hledat stránku nebo záznam
          </label>
          <input
            id={ids.input}
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={options.length > 0}
            aria-controls={ids.list}
            aria-autocomplete="list"
            aria-activedescendant={activeOption ? optionId(activeOption) : undefined}
            aria-describedby={ids.status}
            autoComplete="off"
            spellCheck={false}
            value={query}
            placeholder="Hledat stránku, úkol, transakci, postavu…"
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            className="min-h-12 min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-ink-faint focus:outline-none"
          />
          {search.searching ? <StatusPulse tone="accent" live className="h-2 w-2" /> : null}
          <kbd className="hidden rounded border border-line bg-surface px-1.5 py-0.5 font-mono text-[11px] text-ink-muted sm:inline">Esc</kbd>
          <Button size="sm" variant="ghost" className="sm:hidden" onClick={onClose}>
            Zavřít
          </Button>
        </div>

        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 py-2">
          {search.error ? <ErrorState className="m-2" message="Hledání v datech selhalo – stránky se dají najít dál." onRetry={() => void search.retry()} /> : null}
          {search.empty ? <EmptyState className="m-2">Nic nenalezeno. Zkus jiné slovo nebo název stránky.</EmptyState> : null}
          <div id={ids.list} role="listbox" aria-label="Výsledky hledání">
            {search.groups.map((g) => (
              <div key={g.key} role="group" aria-labelledby={`${ids.list}-g-${g.key}`} className="mb-2 last:mb-0">
                <div id={`${ids.list}-g-${g.key}`} className="px-2 pb-1 pt-2 font-mono text-[11px] uppercase tracking-[0.14em] text-ink-faint">
                  {g.label}
                </div>
                {g.results.map((r) => {
                  const selected = activeOption?.id === r.id;
                  return (
                    <div
                      key={r.id}
                      id={optionId(r)}
                      role="option"
                      aria-selected={selected}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseMove={() => {
                        const i = options.findIndex((o) => o.id === r.id);
                        if (i !== activeIndex) setActive(i);
                      }}
                      onClick={() => openResult(r)}
                      className={cx(
                        "relative flex min-h-11 cursor-pointer items-center gap-3 rounded-[var(--radius-control)] px-2.5 py-1.5 pointer-coarse:min-h-12",
                        selected ? "bg-accent/10 text-ink" : "text-ink-2 hover:bg-surface",
                      )}
                    >
                      {selected ? <span aria-hidden="true" className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent" /> : null}
                      <div className="min-w-0 flex-1">
                        <div className={cx("truncate text-sm", selected ? "font-medium text-ink" : "text-ink")}>{r.title}</div>
                        {r.subtitle ? <div className="truncate text-xs text-ink-muted">{r.subtitle}</div> : null}
                      </div>
                      <span aria-hidden="true" className={cx("w-4 shrink-0 text-xs text-accent-strong", selected ? "visible" : "invisible")}>
                        ↵
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2 text-[11px] text-ink-muted">
          <span className="hidden gap-3 sm:flex">
            <span>
              <kbd className="font-mono">↑ ↓</kbd> vybrat
            </span>
            <span>
              <kbd className="font-mono">Enter</kbd> otevřít
            </span>
            <span>
              <kbd className="font-mono">Esc</kbd> zavřít
            </span>
          </span>
          <span id={ids.status} role="status" aria-live="polite" className="ml-auto tabular-nums">
            {statusText}
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
