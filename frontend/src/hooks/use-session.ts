"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { getSupabase, isAuthConfigured } from "@/lib/supabase";

export type SessionState = {
  session: Session | null;
  email: string | null;
  loading: boolean;
  /** 인증이 설정되지 않은 환경(로컬 dev 모드)에서는 로그인을 요구하지 않는다. */
  authRequired: boolean;
};

export function useSession(): SessionState {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(isAuthConfigured);

  useEffect(() => {
    if (!isAuthConfigured) return;
    const supabase = getSupabase();

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    // 토큰 갱신·로그아웃을 다른 탭에서 해도 여기 반영된다.
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setLoading(false);
    });
    return () => subscription.subscription.unsubscribe();
  }, []);

  return {
    session,
    email: session?.user?.email ?? null,
    loading,
    authRequired: isAuthConfigured,
  };
}
