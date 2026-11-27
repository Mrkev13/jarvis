"use client";

import { useState } from "react";
import { Button, StatusBadge } from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { WotAccount } from "@/lib/wot";

/**
 * MRK-105: propojení s Wargaming účtem – kredity, zlato, volné XP a bondy se pak načítají samy (hodinově a při
 * otevření stránky). Vypršelé přihlášení = jasná výzva „Propojit znovu“, ruční „Upravit zdroje“ funguje dál.
 */
export function WargamingLink({ account, onChange }: { account: WotAccount | null; onChange: () => Promise<unknown> | void }) {
  const [busy, setBusy] = useState<"login" | "sync" | "off" | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!account) return null;

  async function run(kind: "login" | "sync" | "off") {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "login") {
        const { location } = await apiJson<{ location: string }>("/wot/account/login", jsonBody("POST", { origin: window.location.origin }));
        window.location.assign(location);
        return;
      }
      if (kind === "sync") await apiJson("/wot/account/sync", { method: "POST" });
      else await apiJson("/wot/account", { method: "DELETE" });
      await onChange();
    } catch (err) {
      setError(errorMessage(err, "Akce se nepovedla."));
      setBusy(null); // i po chybě přihlášení jde propojení zopakovat bez obnovení stránky
      return;
    }
    setBusy(null); // (úspěšné přihlášení odešlo na Wargaming už výše – tlačítko zůstane „Přesměrovávám…“)
  }

  const expired = account.status === "expired";
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-sm" data-wot-wargaming={account.status}>
      {!account.configured ? (
        <p className="text-ink-muted">
          Automatické zdroje: na serveru chybí {account.missing.join(" a ") || "nastavení"} (docs/wot-resources.md). Zdroje zadávej ručně.
        </p>
      ) : account.connected ? (
        <>
          <StatusBadge tone={account.error ? "warning" : "success"}>Wargaming propojen</StatusBadge>
          <span className="text-ink-muted">
            {account.last_sync_at ? `načteno ${formatDateTime(account.last_sync_at)}` : "zatím nenačteno"}
            {account.error_text ? ` · ${account.error_text}` : ""}
          </span>
          <Button size="sm" variant="ghost" busy={busy === "sync"} busyLabel="Načítám…" onClick={() => void run("sync")}>Načíst teď</Button>
          <Button size="sm" variant="ghost" busy={busy === "off"} onClick={() => void run("off")}>Odpojit</Button>
        </>
      ) : (
        <>
          {expired ? <StatusBadge tone="warning">Přihlášení vypršelo</StatusBadge> : null}
          <span className="text-ink-muted">
            {expired ? account.error_text ?? "Propoj účet znovu." : "Propoj Wargaming účet a kredity, zlato, Free XP i bondy se budou načítat samy."}
          </span>
          <Button size="sm" variant="secondary" busy={busy === "login"} busyLabel="Přesměrovávám…" onClick={() => void run("login")}>
            {expired ? "Propojit znovu" : "Propojit s Wargamingem"}
          </Button>
        </>
      )}
      {error ? <p role="alert" className="w-full text-danger">{error}</p> : null}
    </div>
  );
}
