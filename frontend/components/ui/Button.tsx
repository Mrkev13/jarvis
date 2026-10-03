import Link from "next/link";
import { cx } from "@/lib/ui";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "success";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  // Primární = cyan akcent s jemnou září; jediné „svítící" tlačítko na obrazovce.
  primary: "bg-accent text-app font-semibold hover:bg-accent-strong shadow-[0_0_20px_-8px_rgb(34_211_238/0.6)]",
  secondary: "border border-line bg-surface-2 text-ink hover:bg-hover hover:border-ink-faint",
  ghost: "text-ink-2 hover:bg-hover hover:text-ink",
  danger: "border border-danger/40 text-danger hover:bg-danger/10",
  success: "bg-success/90 text-app font-semibold hover:bg-success",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "min-h-9 px-3 text-sm",
  md: "min-h-10 px-4 text-sm",
};

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", className?: string) {
  return cx(
    "motion-press inline-flex items-center justify-center gap-2 rounded-[var(--radius-control)] font-medium",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70 focus-visible:ring-offset-2 focus-visible:ring-offset-app",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
    className,
  );
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Probíhající akce: tlačítko je zakázané a ukáže `busyLabel`. */
  busy?: boolean;
  busyLabel?: React.ReactNode;
  ref?: React.Ref<HTMLButtonElement>;
};

export function Button({ variant, size, busy, busyLabel, disabled, className, children, type = "button", ref, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={buttonClass(variant, size, className)}
    >
      {busy && busyLabel ? busyLabel : children}
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

/** Textový odkaz „Škola →" v hlavičkách karet. */
export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded text-sm text-ink-muted transition-colors hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
    >
      {children}
    </Link>
  );
}
