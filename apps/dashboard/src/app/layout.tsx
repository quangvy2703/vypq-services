import type { Metadata } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "vypq services",
  description: "Bảng điều khiển các model service",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen">
        <Nav />
        <main className="mx-auto max-w-6xl space-y-6 p-4">{children}</main>
      </body>
    </html>
  );
}
