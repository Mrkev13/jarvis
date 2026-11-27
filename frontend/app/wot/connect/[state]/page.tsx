"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Card, ErrorState, LoadingState } from "@/components/ui";
import { apiJson, errorMessage, jsonBody } from "@/lib/api";
import { connectBody } from "@/lib/wot";

/**
 * MRK-105: sem se vrací přihlášení u Wargamingu (`redirect_uri` = `/wot/connect/<state>`). Parametry (včetně
 * access_tokenu) se hned pošlou backendu a adresa se z historie prohlížeče smaže; pak zpět na /wot.
 */
function Connect() {
  const { state } = useParams<{ state: string }>();
  const query = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    const body = connectBody(String(state ?? ""), new URLSearchParams(query.toString()));
    window.history.replaceState(null, "", "/wot/connect"); // token pryč z adresního řádku i historie
    apiJson("/wot/account/connect", jsonBody("POST", body))
      .then(() => window.location.replace("/wot?wargaming=connected#resources"))
      .catch((err) => setError(errorMessage(err, "Propojení s Wargamingem se nepovedlo.")));
  }, [state, query]);

  return (
    <main id="main-content" className="mx-auto max-w-lg px-4 py-10">
      <Card>
        {error ? (
          <ErrorState message={error} />
        ) : (
          <LoadingState lines={1} label="Propojuji Wargaming účet…" />
        )}
        {error ? <p className="mt-3 text-sm"><a className="underline" href="/wot#resources">Zpět na World of Tanks</a></p> : null}
      </Card>
    </main>
  );
}

export default function WotConnectPage() {
  return (
    <Suspense fallback={null}>
      <Connect />
    </Suspense>
  );
}
