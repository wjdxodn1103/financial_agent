import type { Metadata } from "next";
import { Toaster } from "sonner";

import "./globals.css";

export const metadata: Metadata = {
  title: "AssociateLM",
  description: "주어진 원칙에 따라 작업을 하고, 수행한 작업마다 근거를 한눈에 제시해주는 금융 AI 어시스턴트",
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
