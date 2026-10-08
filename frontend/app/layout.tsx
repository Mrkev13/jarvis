import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import AppShell from "@/components/AppShell";
import { companionBootScript } from "@/lib/jarvisCompanion";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
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
