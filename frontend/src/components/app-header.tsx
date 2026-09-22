"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { useSession } from "@/hooks/use-session";
import { getSupabase } from "@/lib/supabase";

const NAV = [
  { href: "/dashboard", label: "대시보드" },
  { href: "/history", label: "분석 이력" },
  { href: "/saved", label: "저장함" },
  { href: "/settings", label: "설정" },
];

export function AppHeader() {
  const router = useRouter();
  const pathname = usePathname();
  const { email, authRequired, session, isGuest } = useSession();

  // 로그인 화면에서는 네비게이션을 숨긴다.
  if (pathname === "/login") return null;

  async function signOut() {
    await getSupabase().auth.signOut();
    router.replace("/login");
  }

  return (
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
              aria-current={pathname === item.href ? "page" : undefined}
              className={
                "rounded-md px-3 py-1.5 " +
                (pathname === item.href
                  ? "bg-slate-100 font-medium text-slate-900 dark:bg-slate-800 dark:text-white"
                  : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white")
              }
            >
              {item.label}
            </Link>
          ))}
        </nav>

        {authRequired && session && (
          <div className="ml-auto flex items-center gap-3 text-sm">
            {isGuest ? (
              <span
                data-testid="guest-badge"
                title="체험 세션입니다. 데이터가 이 브라우저에만 남고 다른 기기에서는 이어지지 않습니다."
                className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-300"
              >
                체험 모드
              </span>
            ) : (
              <span className="text-slate-500 dark:text-slate-400">{email}</span>
            )}
            <button
              onClick={signOut}
              className="rounded-md px-3 py-1.5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              로그아웃
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
