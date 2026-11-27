"use client";

import { useEffect, useState } from "react";

/**
 * MRK-153: šířka kontejneru grafu v px (ResizeObserver). Grafy přes celou šířku z ní berou viewBox, takže
 * popisky mají na mobilu i desktopu skutečných 10 px a neškálují se se šířkou. Do změření platí `fallback`.
 */
export function useWidth(fallback: number) {
  const [el, ref] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width);
      if (w > 0) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return [ref, width] as const;
}
