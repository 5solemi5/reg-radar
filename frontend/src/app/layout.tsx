import type { Metadata } from "next";

import { AppHeader } from "@/components/app-header";
import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "규제 레이더 — 내 업무에 영향을 주는 규제 변화",
  description:
    "직무·업종·규모에 맞는 규제 변화만 골라, 왜 중요한지와 지금 무엇을 해야 하는지를 근거와 함께 알려줍니다.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <Providers>
          <AppHeader />
          <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
          <footer className="mx-auto max-w-5xl px-4 pb-10 text-xs text-slate-500 dark:text-slate-400">
            이 서비스는 법률 자문이 아니라 AI 기반 규제 모니터링 도구입니다. AI 해석은
            참고용이며, 법적 판단이 필요한 경우 전문가 검토를 받으십시오.
          </footer>
        </Providers>
      </body>
    </html>
  );
}
