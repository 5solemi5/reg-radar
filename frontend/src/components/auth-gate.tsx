"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Spinner } from "@/components/ui";
import { useSession } from "@/hooks/use-session";

/**
 * 보호된 화면을 감싼다 (FR-001).
 *
 * 인증이 설정되지 않은 로컬 환경에서는 통과시킨다 — 백엔드도 그때는 dev
 * 모드로 동작하며, 그 조합은 production에서 기동이 거부된다.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { session, loading, authRequired } = useSession();

  const needsLogin = authRequired && !loading && !session;

  useEffect(() => {
    if (needsLogin) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [needsLogin, router, pathname]);

  if (authRequired && loading) return <Spinner label="세션 확인 중…" />;
  if (needsLogin) return <Spinner label="로그인 화면으로 이동 중…" />;

  return <>{children}</>;
}
