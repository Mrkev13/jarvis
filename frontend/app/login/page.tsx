"use client";

import { useState, FormEvent, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { safeNextPath } from "@/lib/safeNext";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

function goTo(path: string): void {
  // Full-page navigace: client router cache drží prefetch odpovědi z doby před přihlášením
  // (middleware je přesměroval na /login), router.replace by je použil a uživatel by zůstal na loginu.
  window.location.replace(path);
}

function LoginInner() {
  const search = useSearchParams();
  const next = safeNextPath(search.get("next"));

  const [pin, setPin] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [authDisabled, setAuthDisabled] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(`${API_URL.replace(/\/$/, "")}/auth/session/validate`, {
          credentials: "include",
          cache: "no-store",
        });
        if (r.ok) {
          const b = await r.json();
          if (b.auth_disabled) {
            setAuthDisabled(true);
          } else if (b.valid) {
            goTo(next);
          }
        }
      } catch {}
    })();
  }, [next]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr("");
    setLoading(true);
    try {
      const r = await fetch(`${API_URL.replace(/\/$/, "")}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin }),
        credentials: "include",
      });
      const b = await r.json();
      if (b.ok) {
        goTo(next);
        return;
      }
      setErr(b.error || "Neplatný PIN");
    } catch (ex: unknown) {
      if (ex instanceof Error) {
        setErr(ex.message || "Chyba připojení");
      } else {
        setErr("Chyba připojení");
      }
    } finally {
      setLoading(false);
    }
  }

  if (authDisabled) {
    return (
      <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-zinc-900 rounded-lg border border-zinc-800 p-8">
          <h1 className="text-2xl font-bold mb-2">🔓 Auth vypnutý</h1>
          <p className="text-zinc-400 mb-6">
            AUTH_PIN_HASH není nakonfigurován. Přístup je otevřený.
          </p>
          <button
            className="w-full bg-zinc-700 hover:bg-zinc-600 px-4 py-2 rounded"
            onClick={() => goTo(next)}
          >
            Pokračovat → {next === "/" ? "Dashboard" : next}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex items-center justify-center p-6">
      <div className="max-w-md w-full bg-zinc-900 rounded-lg border border-zinc-800 p-8">
        <h1 className="text-2xl font-bold mb-2">🔐 Standa Hub – přihlášení</h1>
        <p className="text-zinc-400 mb-6">
          Zadej PIN kód pro přístup k datům.
        </p>
        <form onSubmit={onSubmit} className="space-y-4">
          <input
            autoFocus
            type="password"
            inputMode="numeric"
            placeholder="PIN kód"
            value={pin}
            onChange={(e) => setPin(e.target.value)}
            className="w-full px-4 py-3 bg-zinc-950 border border-zinc-700 rounded-lg focus:outline-none focus:border-zinc-500 text-lg tracking-[0.5em]"
          />
          {err && (
            <div className="text-sm text-red-400 bg-red-950/50 border border-red-900 rounded p-3">
              {err}
            </div>
          )}
          <button
            disabled={loading || !pin}
            className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-semibold py-3 rounded-lg"
          >
            {loading ? "Probíhá ověření…" : "Přihlásit"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-zinc-950 text-zinc-400 flex items-center justify-center">Načítání…</div>}>
      <LoginInner />
    </Suspense>
  );
}
