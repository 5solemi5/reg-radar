"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Button, Card, Spinner, StateMessage } from "@/components/ui";
import { useSession } from "@/hooks/use-session";
import {
  authErrorMessage,
  getSupabase,
  isAuthConfigured,
  signInAsGuest,
} from "@/lib/supabase";

type Mode = "signin" | "signup";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { session, loading } = useSession();

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const next = params.get("next") || "/dashboard";

  async function handleGuest() {
    setError(null);
    setNotice(null);
    setPending(true);
    try {
      await signInAsGuest();
      router.replace(next);
    } catch (e) {
      setError(authErrorMessage(e instanceof Error ? e.message : String(e)));
    } finally {
      setPending(false);
    }
  }

  useEffect(() => {
    if (session) router.replace(next);
  }, [session, router, next]);

  if (!isAuthConfigured) {
    return (
      <StateMessage
        title="인증이 설정되지 않았습니다"
        description="NEXT_PUBLIC_SUPABASE_URL과 PUBLISHABLE_KEY를 .env.local에 설정하세요. 설정 전에는 로컬 dev 모드로 동작합니다."
      />
    );
  }

  if (loading) return <Spinner label="확인 중…" />;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setNotice(null);

    if (password.length < 6) {
      setError("비밀번호는 6자 이상이어야 합니다.");
      return;
    }

    setPending(true);
    const supabase = getSupabase();
    try {
      if (mode === "signup") {
        const { data, error: signUpError } = await supabase.auth.signUp({
          email,
          password,
        });
        if (signUpError) {
          setError(authErrorMessage(signUpError.message));
          return;
        }
        // 이메일 확인이 켜져 있으면 세션 없이 돌아온다.
        if (!data.session) {
          setNotice(
            "가입 확인 메일을 보냈습니다. 메일의 링크를 클릭한 뒤 로그인해 주세요.",
          );
          setMode("signin");
          return;
        }
      } else {
        const { error: signInError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (signInError) {
          setError(authErrorMessage(signInError.message));
          return;
        }
      }
      router.replace(next);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <header className="mb-6 text-center">
        <h1 className="text-2xl font-semibold">규제 레이더</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          내 업무에 영향을 주는 규제 변화만 골라 근거와 함께 보여줍니다.
        </p>
      </header>

      <Card className="mb-4 space-y-3">
        <div>
          <h2 className="text-sm font-medium">가입 없이 둘러보기</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            이메일 없이 바로 들어갑니다. 예시 프로필을 한 번 눌러 채우고 분석까지
            해볼 수 있습니다. 이 브라우저에만 남으며 다른 기기에서는 이어지지 않습니다.
          </p>
        </div>
        <Button
          type="button"
          onClick={handleGuest}
          disabled={pending}
          data-testid="guest-login"
          className="w-full"
        >
          {pending ? "들어가는 중…" : "체험하기"}
        </Button>
      </Card>

      <Card>
        <div className="mb-5 flex rounded-lg bg-slate-100 p-1 dark:bg-slate-800">
          {(["signin", "signup"] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setMode(value);
                setError(null);
              }}
              aria-pressed={mode === value}
              className={
                "flex-1 rounded-md py-1.5 text-sm font-medium transition " +
                (mode === value
                  ? "bg-white shadow-sm dark:bg-slate-900"
                  : "text-slate-600 dark:text-slate-400")
              }
            >
              {value === "signin" ? "로그인" : "회원가입"}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <label className="block">
            <span className="text-sm font-medium">이메일</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </label>

          <label className="block">
            <span className="text-sm font-medium">비밀번호</span>
            <input
              type="password"
              required
              minLength={6}
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
            {mode === "signup" && (
              <span className="mt-1 block text-xs text-slate-500">6자 이상</span>
            )}
          </label>

          {error && (
            <p role="alert" className="text-sm text-rose-600 dark:text-rose-400">
              {error}
            </p>
          )}
          {notice && (
            <p className="text-sm text-emerald-700 dark:text-emerald-400">{notice}</p>
          )}

          <Button type="submit" disabled={pending} className="w-full">
            {pending
              ? "처리 중…"
              : mode === "signin"
                ? "로그인"
                : "가입하고 시작하기"}
          </Button>
        </form>
      </Card>

      <p className="mt-4 text-center text-xs text-slate-500 dark:text-slate-400">
        이 서비스는 법률 자문이 아니라 AI 기반 규제 모니터링 도구입니다.
      </p>
    </div>
  );
}

const inputClass =
  "mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm " +
  "focus:border-slate-900 focus:outline-none " +
  "dark:border-slate-700 dark:bg-slate-950 dark:focus:border-sky-500";

export default function LoginPage() {
  return (
    <Suspense fallback={<Spinner label="불러오는 중…" />}>
      <LoginForm />
    </Suspense>
  );
}
