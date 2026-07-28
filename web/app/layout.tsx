import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "FareWatch",
  description: "Persistent travel-deal monitoring — real deals, with confidence.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-gray-200 bg-white">
          <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/feed" className="text-lg font-bold tracking-tight">
              Fare<span className="text-blue-600">Watch</span>
            </Link>
            <div className="flex gap-6 text-sm font-medium text-gray-600">
              <Link href="/feed" className="hover:text-gray-900">
                Feed
              </Link>
              <Link href="/watches" className="hover:text-gray-900">
                Watches
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
