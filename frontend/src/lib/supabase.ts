/**
 * Supabase 클라이언트 — **인증에만** 쓴다.
 *
 * 데이터는 전부 우리 FastAPI를 거친다. 브라우저가 DB에 직접 붙는 경로를 두지
 * 않기 위해 프로젝트의 Data API도 꺼 두었다. 여기서 얻는 것은 세션과
 * access token뿐이고, 그 토큰을 백엔드가 JWKS로 검증한다.
 *
 * 여기 쓰이는 두 값은 브라우저에 노출되도록 설계된 공개 값이다. 실제 권한은
 * RLS와 백엔드의 토큰 검증이 통제한다.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const publishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";

/** 설정이 없으면 인증 없이도 화면은 뜨게 한다(로컬 dev 모드 대비). */
export const isAuthConfigured = Boolean(url && publishableKey);

let client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient {
  if (!isAuthConfigured) {
    throw new Error(
      "Supabase 설정이 없습니다. NEXT_PUBLIC_SUPABASE_URL과 PUBLISHABLE_KEY를 확인하세요.",
    );
  }
  client ??= createClient(url, publishableKey, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return client;
}

/** 현재 access token. 없으면 null — 호출자가 로그인으로 보내야 한다. */
export async function getAccessToken(): Promise<string | null> {
  if (!isAuthConfigured) return null;
  const { data } = await getSupabase().auth.getSession();
  return data.session?.access_token ?? null;
}

/** Supabase 인증 오류 메시지를 사용자가 읽을 수 있는 한국어로 바꾼다. */
export function authErrorMessage(message: string): string {
  const map: Record<string, string> = {
    "Invalid login credentials": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "Email not confirmed": "이메일 인증이 완료되지 않았습니다. 받은 편지함을 확인해 주세요.",
    "User already registered": "이미 가입된 이메일입니다. 로그인해 주세요.",
    "Password should be at least 6 characters.":
      "비밀번호는 6자 이상이어야 합니다.",
  };
  return map[message] ?? message;
}
