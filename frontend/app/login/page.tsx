"use client";

import { FormEvent, Suspense, useEffect, useId, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AccentLine, Button, Card, ErrorState, fieldClass, HudFrame, HudLabel, StatusPulse } from "@/components/ui";
import { API_URL, readErrorDetail } from "@/lib/api";
import { loginErrorMessage } from "@/lib/loginError";
import { safeNextPath } from "@/lib/safeNext";
import { cx } from "@/lib/ui";

const BASE = API_URL.replace(/\/$/, "");

function goTo(path: string): void {
  // Full-page navigace: client router cache drží prefetch odpovědi z doby před přihlášením
  // (middleware je přesměroval na /login), router.replace by je použil a uživatel by zůstal na loginu.
  window.location.replace(path);
}

/** Rám přihlášení: bez navigace a zvonku (login není přihlášená stránka – viz components/AppShell). */
function AuthFrame({ children }: { children: React.ReactNode }) {
  return (
    <main id="main-content" className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-3">
          <span
            aria-hidden="true"
            className="grid h-11 w-11 place-items-center rounded-xl border border-accent/40 bg-accent/10 font-mono text-sm font-semibold text-accent-strong shadow-[0_0_24px_-8px_rgb(34_211_238/0.8)]"
          >
            SH
          </span>
          <div>
            <p className="text-lg font-semibold leading-tight text-ink">Standa Hub</p>
            <HudLabel className="flex items-center gap-1.5 text-[10px]">
              <StatusPulse tone="accent" className="h-1.5 w-1.5" /> osobní řídicí centrum
            </HudLabel>
          </div>
        </div>
        <HudFrame>
          <Card className="overflow-hidden p-0 md:p-0">
            <AccentLine />
            <div className="p-6">{children}</div>
          </Card>
        </HudFrame>
      </div>
    </main>
  );
}

function LoginInner() {
  const search = useSearchParams();
  const next = safeNextPath(search.get("next"));
  const pinId = useId();
  const hintId = useId();

  const [pin, setPin] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [authDisabled, setAuthDisabled] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${BASE}/auth/session/validate`, { credentials: "include", cache: "no-store" });
        if (r.ok) {
          const b = await r.json();
          if (b.auth_disabled) setAuthDisabled(true);
          else if (b.valid) goTo(next);
        }
      } catch {
        // backend nedostupný – formulář zůstane, chyba se ukáže až při pokusu o přihlášení
      }
    })();
  }, [next]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      const r = await fetch(`${BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
        credentials: "include",
      });
      let body: { ok?: boolean; error?: string } = {};
      try {
        body = await r.clone().json();
      } catch {
        // ne-JSON (proxy / HTML chyba) – níže obecná hláška
      }
      if (r.ok && body.ok) {
        goTo(next);
        return;
      }
      setErr(body.error || r.ok ? loginErrorMessage(body.error) : loginErrorMessage(await readErrorDetail(r)));
    } catch {
      setErr("Nepodařilo se spojit se serverem. Běží backend?");
    } finally {
      setLoading(false);
    }
  }

  if (authDisabled) {
    return (
      <AuthFrame>
        <h1 className="text-xl font-semibold text-ink">Přihlášení je vypnuté</h1>
        <p className="mt-2 text-sm text-ink-2">AUTH_PIN_HASH není nastavený, přístup je otevřený.</p>
        <Button variant="primary" className="mt-6 w-full" onClick={() => goTo(next)}>
          Pokračovat do aplikace
        </Button>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame>
      <h1 className="text-xl font-semibold text-ink">Přihlášení</h1>
      <p className="mt-1 text-sm text-ink-muted">Zadej PIN pro přístup ke svým datům.</p>
      <form onSubmit={onSubmit} className="mt-5 space-y-4" aria-busy={loading}>
        <div className="space-y-1.5">
          <label htmlFor={pinId} className="block text-xs font-medium text-ink-2">
            PIN
          </label>
          <input
            id={pinId}
            autoFocus
            type="password"
            inputMode="numeric"
            autoComplete="current-password"
            aria-describedby={hintId}
            aria-invalid={err ? true : undefined}
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            className={cx(fieldClass, "min-h-12 text-center text-lg tracking-[0.5em]")}
          />
          <p id={hintId} className="text-xs text-ink-muted">
            Po přihlášení zůstaneš přihlášený na tomto zařízení.
          </p>
        </div>
        {err ? <ErrorState message={err} /> : null}
        <Button type="submit" variant="primary" className="w-full" busy={loading} busyLabel="Ověřuji…" disabled={!pin}>
          Přihlásit
        </Button>
      </form>
    </AuthFrame>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div role="status" className="flex min-h-screen items-center justify-center text-sm text-ink-muted">
          Načítám…
        </div>
      }
    >
      <LoginInner />
    </Suspense>
  );
}
