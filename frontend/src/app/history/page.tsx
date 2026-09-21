"use client";

import Link from "next/link";

import { Card, SectionTitle, Spinner, StateMessage } from "@/components/ui";
import { useAnalysisHistory } from "@/hooks/use-analysis";
import { ANALYSIS_STATUS_META, formatDateTime } from "@/lib/display";

export default function HistoryPage() {
  const { data, isLoading, error } = useAnalysisHistory();

  if (isLoading) return <Spinner label="이력을 불러오는 중…" />;
  if (error) {
    return (
      <StateMessage
        tone="error"
        title="이력을 불러오지 못했습니다"
        description={error instanceof Error ? error.message : undefined}
      />
    );
  }

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">분석 이력</h1>
      <SectionTitle hint="과거 분석은 당시 사용한 법령 원문과 판정을 그대로 보존합니다.">
        지난 분석 {data?.total ?? 0}건
      </SectionTitle>

      {data && data.items.length === 0 && (
        <StateMessage
          title="아직 분석 이력이 없습니다"
          description={<Link href="/dashboard" className="underline">대시보드에서 첫 분석을 실행해 보세요.</Link>}
        />
      )}

      <ul className="space-y-3">
        {data?.items.map((analysis) => {
          const status = ANALYSIS_STATUS_META[analysis.status];
          return (
            <li key={analysis.analysis_id}>
              <Card>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-sm font-medium">
                    {formatDateTime(analysis.created_at)}
                  </p>
                  <span className={`text-xs font-medium ${status.tone}`}>{status.label}</span>
                </div>

                {analysis.status === "COMPLETED" && (
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
                    법령 {analysis.laws_examined}건 · 변경 조문 {analysis.articles_changed}건 ·
                    {" "}조치 {analysis.counts.action} / 결정 {analysis.counts.decision} /
                    {" "}인지 {analysis.counts.awareness} / 보류 {analysis.counts.hold}
                  </p>
                )}

                {analysis.status === "FAILED" && analysis.error && (
                  <p className="mt-2 text-sm text-rose-600 dark:text-rose-400">{analysis.error}</p>
                )}

                {analysis.law_query && (
                  <p className="mt-1 text-xs text-slate-500">대상: {analysis.law_query}</p>
                )}
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
