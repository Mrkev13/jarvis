import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { companionBootScript } from "@/lib/jarvisCompanion";

const geistSans = localFont({
  src: "./fonts/Geist.ttf",
  weight: "100 900",
  display: "swap",
  variable: "--font-geist-sans",
});

const geistMono = localFont({
  src: "./fonts/GeistMono.ttf",
  weight: "100 900",
  display: "swap",
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "Standa Hub",
  description: "Personal dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="cs"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // data-jarvis-companion nastavuje skript níže ještě před hydratací
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: companionBootScript() }} />
      </head>
      <body className="min-h-full bg-app font-sans text-ink">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
