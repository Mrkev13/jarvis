"use client";

import { usePathname } from "next/navigation";

/** Jemný vstup obsahu při přechodu na jinou stránku (klíčováno cestou). */
export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div key={pathname} className="motion-page">
      {children}
    </div>
  );
}
