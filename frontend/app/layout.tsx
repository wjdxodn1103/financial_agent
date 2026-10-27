import type { Metadata } from "next";
import { Toaster } from "sonner";

import "./globals.css";

export const metadata: Metadata = {
  title: "DCF",
  description: "Document Creation & Fact-check — 금융 문서 작성·검수 AI 에이전트",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="antialiased">
        {children}
        <Toaster richColors />
      </body>
    </html>
  );
}
