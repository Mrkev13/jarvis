// Chybové kódy z POST /auth/login → česká hláška (backend vrací kódy, ne text pro uživatele).

const LOCKED_RE = /locked for (\d+)\s*s/i;

export function loginErrorMessage(code: string | null | undefined): string {
  const raw = (code || "").trim();
  if (!raw || raw === "invalid_pin" || raw === "invalid_credentials") return "Neplatný PIN.";
  const locked = LOCKED_RE.exec(raw);
  if (locked) {
    const minutes = Math.max(1, Math.ceil(Number(locked[1]) / 60));
    return `Příliš mnoho neúspěšných pokusů. Zkus to znovu za ${minutes} min.`;
  }
  if (/too many/i.test(raw)) return "Příliš mnoho neúspěšných pokusů. Zkus to prosím později.";
  return raw;
}
