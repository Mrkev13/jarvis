/**
 * MRK-152: „Přidat replay“ na přehledu WoT – soubor vybraný tam se předá knihovně replayů (`/wot/replays?upload=1`),
 * která ho nahraje stejnou cestou jako vlastní tlačítko (kontrola, tank z manifestu, kontrola údajů). Jen v paměti
 * klientské navigace; po obnovení stránky se zahodí (vybere se znovu).
 */
let pending: File | null = null;

export function setPendingReplay(file: File): void {
  pending = file;
}

/** Vrátí a zároveň vymaže čekající soubor (nahraje se nejvýš jednou). */
export function takePendingReplay(): File | null {
  const file = pending;
  pending = null;
  return file;
}
