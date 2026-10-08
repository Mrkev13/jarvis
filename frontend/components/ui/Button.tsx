import Link from "next/link";
import type { IconName } from "@/lib/icons";
import { cx } from "@/lib/ui";
import { Icon } from "./Icon";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  // Primární = cyan akcent s jemnou září; jediné „svítící" tlačítko na obrazovce.
  primary: "bg-accent text-app font-semibold hover:bg-accent-strong shadow-[0_0_20px_-8px_rgb(34_211_238/0.6)]",
  secondary: "border border-line bg-surface-2 text-ink hover:bg-hover hover:border-ink-faint",
  ghost: "text-ink-2 hover:bg-hover hover:text-ink",
  danger: "border border-danger/40 text-danger hover:bg-danger/10",
  // Obrys jako danger: jasně akční, ale nepřebije primární tlačítko (plná zelená na každém řádku byla nejhlasitější).
  success: "border border-success/45 text-success hover:bg-success/10 hover:border-success/70",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3 text-sm pointer-coarse:min-h-11",
  md: "min-h-10 px-4 text-sm pointer-coarse:min-h-11",
};
// Čtvercové tlačítko jen s ikonou (IconButton) – stejná výška jako textové tlačítko téže velikosti.
const SQUARE: Record<ButtonSize, string> = {
  sm: "h-9 w-9 pointer-coarse:h-11 pointer-coarse:w-11",
  md: "h-10 w-10 pointer-coarse:h-11 pointer-coarse:w-11",
};

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string, square = false) {
  return cx(
    "motion-press inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] font-medium",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 focus-visible:ring-offset-2 focus-visible:ring-offset-app",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    square ? SQUARE[size] : SIZE[size],
    className,
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Probíhající akce: tlačítko je zakázané a ukáže `busyLabel`. */
  busy?: boolean;
  busyLabel?: React.ReactNode;
  /** Volitelná ikona před textem (MRK-15) – text zůstává. */
  icon?: IconName;
  ref?: React.Ref<HTMLButtonElement>;
};

export function Button({ variant, size, busy, busyLabel, icon, disabled, className, children, type = "button", ref, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={buttonClass(variant, size, className)}
    >
      {icon && !(busy && busyLabel) ? <Icon name={icon} size="sm" /> : null}
      {busy && busyLabel ? busyLabel : children}
    </button>
  );
}

/**
 * Tlačítko jen s ikonou (MRK-15, varianta „subtle"): čtverec se stejnou výškou jako Button téže velikosti,
 * na dotyk ≥ 44 px. `label` je povinný – stane se přístupným názvem (a tooltipem).
 */
export function IconButton({
  icon,
  label,
  variant = "ghost",
  size = "sm",
  pressed,
  filled,
  className,
  ref,
  ...rest
}: Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> & {
  icon: IconName;
  label: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Přepínač (aria-pressed), např. oblíbené. */
  pressed?: boolean;
  filled?: boolean;
  ref?: React.Ref<HTMLButtonElement>;
}) {
  return (
    <button
      {...rest}
      ref={ref}
      type={rest.type ?? "button"}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      className={buttonClass(variant, size, className, true)}
    >
      <Icon name={icon} size={size === "sm" ? "sm" : "md"} filled={filled} />
    </button>
  );
}

export function ButtonLink({
  href,
  variant,
  size,
  className,
  children,
}: {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link href={href} className={buttonClass(variant, size, className)}>
      {children}
    </Link>
  );
}

/** Textový odkaz „Škola →" v hlavičkách karet; dotyková plocha je větší než text. */
export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className={cx(
        "relative inline-flex items-center rounded text-sm text-ink-muted transition-colors hover:text-accent-strong",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70",
        // neviditelná zvětšená plocha pro dotyk (~44 px) bez změny vzhledu a rozložení
        "after:absolute after:-inset-x-2 after:-inset-y-3 after:content-['']",
      )}
    >
      {children}
    </Link>
  );
}
