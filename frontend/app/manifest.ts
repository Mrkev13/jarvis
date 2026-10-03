import type { MetadataRoute } from "next";

// Phase E: manifest kvůli instalaci na plochu (na iOS jediná cesta k Web Push upozorněním).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Standa Hub",
    short_name: "Standa Hub",
    description: "Osobní dashboard – finance, práce, škola, cíle a připomínky.",
    start_url: "/",
    display: "standalone",
    background_color: "#09090b",
    theme_color: "#09090b",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
