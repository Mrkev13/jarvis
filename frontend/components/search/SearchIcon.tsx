/** Lupa (inline SVG, barva podle textu). */
export function SearchIcon({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className={className ?? "h-4 w-4"}>
      <circle cx="8.5" cy="8.5" r="5.5" />
      <path d="M12.6 12.6 17 17" />
    </svg>
  );
}
