import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "AI Cut Editor" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-neutral-50 text-neutral-900">{children}</body>
    </html>
  );
}
