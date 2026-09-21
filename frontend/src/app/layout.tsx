import type { Metadata } from "next";
import Link from "next/link";

import { Providers } from "@/components/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "규제 레이더 — 내 업무에 영향을 주는 규제 변화",
  description:
    "직무·업종·규모에 맞는 규제 변화만 골라, 왜 중요한지와 지금 무엇을 해야 하는지를 근거와 함께 알려줍니다.",
};

const NAV = [
  { href: "/dashboard", label: "대시보드" },
  { href: "/history", label: "분석 이력" },
  { href: "/saved", label: "저장함" },
  { href: "/settings", label: "설정" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <Providers>
          <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
              <Link href="/dashboard" className="text-base font-semibold">
                규제 레이더
              </Link>
              <nav className="flex gap-1 text-sm" aria-label="주요 메뉴">
                {NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>

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
