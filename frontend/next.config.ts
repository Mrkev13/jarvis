import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Dev server přes Tailscale (http://100.102.110.1:3000): bez toho Next.js blokuje dev zdroje
  // (/_next/*, HMR) z jiného hostu než localhost a stránka se nehydratuje.
  allowedDevOrigins: ["100.102.110.1"],
  // Phase E: service worker pro Web Push – vždy čerstvá verze, jen vlastní skripty.
  async headers() {
    return [
      {
        source: "/sw.js",
        headers: [
          { key: "Content-Type", value: "application/javascript; charset=utf-8" },
          { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
          { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self'" },
        ],
      },
    ];
  },
};

export default nextConfig;
