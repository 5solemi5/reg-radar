"use client";

import { useRouter } from "next/navigation";

import { ProfileForm } from "@/components/profile-form";
import { Spinner } from "@/components/ui";
import { useProfile, useSaveProfile } from "@/hooks/use-profile";
import { AuthGate } from "@/components/auth-gate";

function OnboardingPageContent() {
  const router = useRouter();
  const { profile, isLoading } = useProfile();
  const save = useSaveProfile();

  if (isLoading) {
    return <Spinner label="불러오는 중…" />;
  }

  return (
    <div className="mx-auto max-w-2xl">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">업무 프로필 설정</h1>
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          입력한 정보로 <strong>내 업무에 영향을 주는 규제 변화만</strong> 골라냅니다.
          법령 원문은 법제처에서 직접 가져오고, AI는 그것이 내 상황에 어떤 의미인지만
          해석합니다.
        </p>
      </header>

      <ProfileForm
        initial={profile}
        submitLabel="저장하고 시작하기"
        pending={save.isPending}
        errorMessage={save.error instanceof Error ? save.error.message : null}
        onSubmit={(input) =>
          save.mutate(input, { onSuccess: () => router.push("/dashboard") })
        }
      />
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <AuthGate>
      <OnboardingPageContent />
    </AuthGate>
  );
}
