/**
 * Filtry seznamů (Roadmap 4B – FilterBar v Aktivitě a Paměti). Čisté funkce, testy: filters.test.mjs.
 */
export type FilterValue = string | number | boolean | null | undefined | ReadonlyArray<string>;

/** Prázdná hodnota = filtr se neuplatní („all", "", false, [], null). */
export function isEmptyFilter(value: FilterValue): boolean {
  if (value == null || value === false) return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "string") return value.trim() === "" || value === "all";
  return false;
}

/** Query string bez prázdných filtrů; pole se spojí čárkou, řetězce se ořežou. Pořadí klíčů zůstává. */
export function filterQuery(params: Record<string, FilterValue>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (isEmptyFilter(value)) continue;
    if (Array.isArray(value)) qs.set(key, value.join(","));
    else qs.set(key, typeof value === "string" ? value.trim() : String(value));
  }
  return qs.toString();
}

/** Počet aktivních filtrů (pro „Zrušit filtry (2)"). */
export function countActiveFilters(params: Record<string, FilterValue>): number {
  return Object.values(params).filter((v) => !isEmptyFilter(v)).length;
}

/** Přepnutí položky v multi-výběru (čipy) – vrací nové pole, pořadí podle `order`. */
export function toggleInList(list: ReadonlyArray<string>, item: string, order?: ReadonlyArray<string>): string[] {
  const next = list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
  return order ? order.filter((x) => next.includes(x)) : next;
}
