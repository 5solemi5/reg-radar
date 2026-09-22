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

/**
 * 체험용 익명 로그인.
 *
 * 이메일도 비밀번호도 받지 않고 바로 들어간다. 심사나 데모에서 가입 절차가
 * 서비스를 보기도 전에 포기하게 만드는 문턱이기 때문이다.
 *
 * 공용 계정을 쓰지 않는 이유는 둘이다. 공개 저장소·공개 사이트에 비밀번호를
 * 적어야 하고, 들어온 사람들이 서로의 데이터를 보게 된다. 익명 로그인은
 * 사람마다 별도의 사용자를 만들어 준다.
 *
 * 세션은 이 브라우저에만 남는다. 다른 기기에서는 이어서 볼 수 없다.
 */
export async function signInAsGuest(): Promise<void> {
  const { error } = await getSupabase().auth.signInAnonymously();
  if (error) throw error;
}

/** Supabase 인증 오류 메시지를 사용자가 읽을 수 있는 한국어로 바꾼다. */
export function authErrorMessage(message: string): string {
  const map: Record<string, string> = {
    "Invalid login credentials": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "Email not confirmed": "이메일 인증이 완료되지 않았습니다. 받은 편지함을 확인해 주세요.",
    "User already registered": "이미 가입된 이메일입니다. 로그인해 주세요.",
    "Password should be at least 6 characters.":
      "비밀번호는 6자 이상이어야 합니다.",
    // 프로젝트에서 익명 로그인을 켜지 않았을 때. 무엇을 켜야 하는지까지 말해준다.
    "Anonymous sign-ins are disabled":
      "체험 로그인이 꺼져 있습니다. Supabase → Authentication → Sign In/Providers에서 " +
      "Anonymous sign-ins를 켜야 합니다.",
  };
  return map[message] ?? message;
}
