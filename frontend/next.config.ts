import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Dev server přes Tailscale (http://100.102.110.1:3000): bez toho Next.js blokuje dev zdroje
  // (/_next/*, HMR) z jiného hostu než localhost a stránka se nehydratuje.
  allowedDevOrigins: ["100.102.110.1"],
};

export default nextConfig;
