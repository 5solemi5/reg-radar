"use client";

import { ProfileForm } from "@/components/profile-form";
import { Spinner, StateMessage } from "@/components/ui";
import { useProfile, useSaveProfile } from "@/hooks/use-profile";
import { AuthGate } from "@/components/auth-gate";

function SettingsPageContent() {
  const { profile, isLoading, needsOnboarding } = useProfile();
  const save = useSaveProfile();

  if (isLoading) return <Spinner label="불러오는 중…" />;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-2 text-2xl font-semibold">프로필 설정</h1>
      <p className="mb-6 text-sm text-slate-600 dark:text-slate-400">
        프로필을 바꾸면 <strong>다음 분석부터</strong> 반영됩니다. 지난 분석 결과는 당시
        기준으로 그대로 보존됩니다.
      </p>

      {needsOnboarding && (
        <StateMessage
          title="아직 프로필이 없습니다"
          description="아래에서 입력하면 바로 분석을 시작할 수 있습니다."
        />
      )}

      <div className="mt-6">
        <ProfileForm
          initial={profile}
          submitLabel="변경 사항 저장"
          pending={save.isPending}
          errorMessage={save.error instanceof Error ? save.error.message : null}
          onSubmit={(input) => save.mutate(input)}
        />
      </div>

      {save.isSuccess && (
        <p className="mt-4 text-sm text-emerald-600 dark:text-emerald-400">저장되었습니다.</p>
      )}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <AuthGate>
      <SettingsPageContent />
    </AuthGate>
  );
}
