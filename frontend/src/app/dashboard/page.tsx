"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ResultCard } from "@/components/result-card";
import { Button, Card, SectionTitle, Spinner, StateMessage } from "@/components/ui";
import { useResults, useRunAnalysis } from "@/hooks/use-analysis";
import { useProfile } from "@/hooks/use-profile";
import { COMPANY_SIZE_OPTIONS } from "@/lib/display";
import type { Counts } from "@/lib/schemas";
import { AuthGate } from "@/components/auth-gate";

function DashboardPageContent() {
  const router = useRouter();
  const { profile, needsOnboarding, isLoading, error } = useProfile();
  const { start, analysis, activeId, isRunning, startError } = useRunAnalysis();
  const [showNotApplicable, setShowNotApplicable] = useState(false);
  const [lawQuery, setLawQuery] = useState("");

  const completed = analysis?.status === "COMPLETED";
  const results = useResults(completed ? activeId : null, showNotApplicable);

  // 프로필이 없으면 온보딩이 먼저다 (FR-002 AC).
  useEffect(() => {
    if (needsOnboarding) router.replace("/onboarding");
  }, [needsOnboarding, router]);

  if (isLoading) return <Spinner label="프로필을 불러오는 중…" />;

  if (error) {
    return (
      <StateMessage
        tone="error"
        title="프로필을 불러오지 못했습니다"
        description={error instanceof Error ? error.message : "알 수 없는 오류"}
        action={<Button onClick={() => location.reload()}>다시 시도</Button>}
      />
    );
  }

  if (!profile) return <Spinner label="이동 중…" />;

  const sizeLabel =
    COMPANY_SIZE_OPTIONS.find((o) => o.value === profile.company_size)?.label ??
    profile.company_size;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">규제 대시보드</h1>
          <p className="mt-1.5 text-sm text-slate-600 dark:text-slate-400">
            {profile.job} · {profile.industry} · {sizeLabel}
            {profile.employee_count != null && ` · ${profile.employee_count}명`}
          </p>
          {profile.interests.length > 0 && (
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              관심 영역({profile.interests.join(", ")}) 기준으로 법령을 고릅니다.
            </p>
          )}
          {profile.employee_count == null && (
            <p className="mt-1 text-xs text-amber-700 dark:text-amber-400">
              상시근로자 수가 없어 규모 기준이 있는 조문은 보류로 나옵니다.{" "}
              <Link href="/settings" className="underline">
                입력하기
              </Link>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={lawQuery}
            onChange={(e) => setLawQuery(e.target.value)}
            placeholder="특정 법령만 (예: 근로기준법)"
            aria-label="분석할 법령 이름"
            className="w-56 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
          />
          <Button
            onClick={() =>
              start.mutate({ max_laws: 3, law_query: lawQuery.trim() || undefined })
            }
            disabled={isRunning}
          >
            {isRunning ? "분석 중…" : "규제 변화 분석"}
          </Button>
        </div>
      </header>

      {/* 한도 소진은 고장이 아니라 설계된 상한이다. 빨간 오류로 보여주면
          사용자가 뭔가 잘못한 것처럼 읽힌다. */}
      {startError?.isDailyLimit && (
        <StateMessage
          tone="info"
          title="오늘의 분석 한도를 모두 썼습니다"
          description={`${startError.message} 이 서비스는 AI 호출 비용을 유한하게 묶기 위해 하루 실행 횟수를 제한합니다.`}
        />
      )}

      {startError && !startError.isAnalysisInProgress && !startError.isDailyLimit && (
        <StateMessage tone="error" title="분석을 시작하지 못했습니다" description={startError.message} />
      )}

      {/* 진행 상태를 빈 화면 대신 명시한다 (NFR-006, NFR-013). */}
      {isRunning && (
        <Card>
          <Spinner label="법제처에서 변경된 조문을 찾고 AI가 판단하는 중입니다…" />
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            법령을 가져와 조문마다 판단합니다. <strong className="font-medium">보통 2~4분</strong> 걸리며,
            무료 서버라 더 느릴 수 있습니다. 창을 닫았다 와도 진행 상황이 이어집니다.
          </p>
        </Card>
      )}

      {analysis?.status === "FAILED" && (
        <StateMessage
          tone="error"
          title="분석에 실패했습니다"
          description={analysis.error ?? "원인을 확인할 수 없습니다."}
          action={<Button onClick={() => start.mutate({ max_laws: 3, law_query: lawQuery.trim() || undefined })}>다시 시도</Button>}
        />
      )}

      {completed && analysis && (
        <>
          <section>
            <SectionTitle hint={`법령 ${analysis.laws_examined}건에서 변경 조문 ${analysis.articles_changed}건을 분석했습니다.`}>
              요약
            </SectionTitle>
            <CountsGrid counts={analysis.counts} />
          </section>

          <section>
            <div className="mb-3 flex items-end justify-between">
              <SectionTitle hint="지금 해야 할 일과 결정이 필요한 변화를 위에 둡니다.">
                분석 결과
              </SectionTitle>
              <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                <input
                  type="checkbox"
                  checked={showNotApplicable}
                  onChange={(e) => setShowNotApplicable(e.target.checked)}
                  className="size-4"
                />
                무관 항목도 보기
              </label>
            </div>

            {results.isLoading && <Spinner label="결과를 불러오는 중…" />}

            {results.data && results.data.items.length === 0 && (
              <StateMessage
                title="표시할 결과가 없습니다"
                description={
                  showNotApplicable
                    ? "이번 분석에서 변경된 조문이 없거나 모두 검증에서 제외되었습니다."
                    : "내게 해당하거나 보류인 항목이 없습니다. 무관 항목도 보려면 위 체크박스를 켜세요."
                }
              />
            )}

            <div className="space-y-4">
              {results.data?.items.map((result) => (
                <ResultCard key={result.result_id} result={result} />
              ))}
            </div>
          </section>
        </>
      )}

      {!analysis && !isRunning && (
        <StateMessage
          title="아직 분석한 규제 변화가 없습니다"
          description="‘최근 규제 변화 분석’을 누르면 법제처에서 최근 개정된 법령을 가져와 내 프로필 기준으로 판단합니다."
          action={<Button onClick={() => start.mutate({ max_laws: 3, law_query: lawQuery.trim() || undefined })}>지금 분석하기</Button>}
        />
      )}
    </div>
  );
}

function CountsGrid({ counts }: { counts: Counts }) {
  const cells = [
    { label: "조치 필요", value: counts.action, tone: "text-rose-600 dark:text-rose-400" },
    { label: "방침 결정", value: counts.decision, tone: "text-orange-600 dark:text-orange-400" },
    { label: "인지", value: counts.awareness, tone: "text-sky-600 dark:text-sky-400" },
    { label: "보류", value: counts.hold, tone: "text-amber-600 dark:text-amber-400" },
    { label: "무관", value: counts.not_applicable, tone: "text-slate-500" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {cells.map((cell) => (
        <Card key={cell.label} className="p-4">
          <p className="text-xs text-slate-500 dark:text-slate-400">{cell.label}</p>
          <p className={`mt-1 text-2xl font-semibold ${cell.tone}`}>{cell.value}</p>
        </Card>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGate>
      <DashboardPageContent />
    </AuthGate>
  );
}
