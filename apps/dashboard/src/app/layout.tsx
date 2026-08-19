import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "vypq services",
  description: "Bảng điều khiển các model service",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}
