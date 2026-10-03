import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { DesktopSidebar, MobileHeader } from "@/components/Sidebar";
import { PageTransition } from "@/components/motion/PageTransition";

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
    >
      <body className="min-h-full bg-app font-sans text-ink">
        <div className="flex min-h-screen">
          <DesktopSidebar />
          <div className="hud-grid flex-1 flex flex-col min-w-0">
            <MobileHeader />
            <div className="flex-1">
              <PageTransition>{children}</PageTransition>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
