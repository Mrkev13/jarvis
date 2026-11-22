"use client";

import { useEffect, useId, useRef, useState } from "react";

import type { IconName } from "@/lib/icons";
import { cx } from "@/lib/ui";
import { buttonClass, type ButtonVariant } from "./Button";
import { Icon } from "./Icon";

export type ActionMenuItem = {
  label: string;
  /** Přístupný název (např. „Zrušit připomínku: Fyzio") – výchozí je `label`. */
  ariaLabel?: string;
  onSelect: () => void;
  tone?: "danger";
  disabled?: boolean;
};

/**
 * MRK-123: tlačítko s nabídkou akcí (WAI-ARIA menu button) – jedno hlavní tlačítko v řádku, ostatní akce tady.
 * Otevře klik, Enter, mezerník i šipka dolů (fokus na první položku), šipka nahoru (na poslední). V nabídce šipky,
 * Home/End; Escape zavře a vrátí fokus na tlačítko, Tab nabídku zavře. Klik mimo zavře. Položky ≥ 44 px na dotyku.
 * Bez textu (`icon` bez `label`) jen s `ariaLabel` – např. „Další akce: Fyzioterapie" (⋯).
 */
export function ActionMenu({
  label,
  icon,
  ariaLabel,
  items,
  variant = "secondary",
  disabled,
  className,
  focusKey,
}: {
  label?: string;
  icon?: IconName;
  ariaLabel: string;
  items: ActionMenuItem[];
  variant?: ButtonVariant;
  disabled?: boolean;
  className?: string;
  /** `data-focus-key` tlačítka – stránka na něj umí vrátit fokus (MRK-125: dashboard po „Hotovo"). */
  focusKey?: string;
}) {
  const [open, setOpen] = useState(false);
  const [alignStart, setAlignStart] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const menuItems = () => Array.from(wrapRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []);
  const focusItem = (index: number) => {
    const all = menuItems();
    if (all.length) all[(index + all.length) % all.length].focus();
  };

  const show = (focus: "first" | "last") => {
    // u levého okraje (mobil: akce zarovnané vlevo) se nabídka otevře doprava, jinak doleva od tlačítka
    const rect = triggerRef.current?.getBoundingClientRect();
    setAlignStart(Boolean(rect && rect.right < 240));
    setOpen(true);
    requestAnimationFrame(() => focusItem(focus === "first" ? 0 : -1));
  };
  const close = (returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  const onMenuKey = (e: React.KeyboardEvent) => {
    const all = menuItems();
    const current = all.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") { e.preventDefault(); focusItem(current + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusItem(current - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusItem(0); }
    else if (e.key === "End") { e.preventDefault(); focusItem(-1); }
    else if (e.key === "Tab") setOpen(false);
  };

  return (
    <div
      ref={wrapRef}
      className={cx("relative inline-flex", className)}
      data-action-menu=""
      // Escape kdekoli v komponentě (i na tlačítku hned po otevření, než fokus přejde do nabídky)
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) { e.preventDefault(); e.stopPropagation(); close(true); }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        data-focus-key={focusKey}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        className={buttonClass(variant, "sm", "gap-1", !label)}
        onClick={() => (open ? close(false) : show("first"))}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); show("first"); }
          else if (e.key === "ArrowUp") { e.preventDefault(); show("last"); }
        }}
      >
        {icon ? <Icon name={icon} size="sm" /> : null}
        {label ? <span>{label}</span> : null}
        {label ? <Icon name="chevron-down" size="sm" className="opacity-70" /> : null}
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          aria-label={ariaLabel}
          onKeyDown={onMenuKey}
          className={cx(
            "absolute top-full z-30 mt-1 min-w-44 overflow-hidden rounded-[var(--radius-control)] border border-line bg-elevated p-1 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.8)]",
            alignStart ? "left-0" : "right-0",
          )}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              tabIndex={-1}
              disabled={item.disabled}
              aria-label={item.ariaLabel ?? item.label}
              onClick={() => {
                close(true);
                item.onSelect();
              }}
              className={cx(
                "flex min-h-9 w-full items-center rounded-md px-3 text-left text-sm pointer-coarse:min-h-11",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 disabled:opacity-50",
                item.tone === "danger" ? "text-danger hover:bg-danger/10 focus:bg-danger/10" : "text-ink hover:bg-hover focus:bg-hover",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
