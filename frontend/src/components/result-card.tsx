import Link from "next/link";

import { ActionGradeChip, ApplicabilityChip, Card } from "@/components/ui";
import { CHANGE_TYPE_LABEL, effectiveDateNote, formatDate } from "@/lib/display";
import type { Result } from "@/lib/schemas";

export function ResultCard({ result }: { result: Result }) {
  const legal = result.legal_evidence;
  const ai = result.ai_interpretation;
  const note = effectiveDateNote(legal.effective_date);

  return (
    // data 속성은 E2E가 판정별로 카드를 안정적으로 찾기 위한 것이다.
    // 문구로 찾으면 카피가 바뀔 때마다 테스트가 깨진다.
    <Card
      className="transition hover:border-slate-300 dark:hover:border-slate-700"
      data-testid="result-card"
      data-applicability={result.applicability}
    >
      <div className="flex flex-wrap items-center gap-2">
        <ApplicabilityChip value={result.applicability} />
        {result.action_grade && <ActionGradeChip value={result.action_grade} />}
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {CHANGE_TYPE_LABEL[result.change.change_type] ?? result.change.change_type}
        </span>
      </div>

      <h3 className="mt-3 text-base font-semibold">
        <Link href={`/results/${result.result_id}`} className="hover:underline">
          {legal.law_name} {legal.article_no}
          {legal.article_title && (
            <span className="font-normal text-slate-600 dark:text-slate-400">
              {" "}
              · {legal.article_title}
            </span>
          )}
        </Link>
      </h3>

      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        시행 {formatDate(legal.effective_date)}
        {note && <span className="ml-2 text-slate-400">({note})</span>}
        {legal.ministry && <span className="ml-2">· {legal.ministry}</span>}
      </p>

      <p className="mt-3 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
        {ai.impact_summary ?? ai.reason}
      </p>

      {/* 보류는 '무엇을 넣으면 풀리는지'를 바로 보여준다 (FR-008). */}
      {result.applicability === "HOLD" && ai.missing_context.length > 0 && (
        <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
          <p className="font-medium text-amber-900 dark:text-amber-300">
            이 정보가 있으면 확정할 수 있습니다
          </p>
          <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-amber-800 dark:text-amber-400">
            {ai.missing_context.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {ai.checklist.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-700 dark:text-slate-300">
          {ai.checklist.slice(0, 3).map((item) => (
            <li key={item.title} className="flex gap-2">
              <span aria-hidden className="text-slate-400">
                ☐
              </span>
              {item.title}
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="text-slate-500 dark:text-slate-400">
          검증된 원문 인용 {legal.quoted_spans.length}건
          {result.delegated_evidence.length > 0 && (
            <span className="ml-1">· 시행령 {result.delegated_evidence.length}건</span>
          )}
          {result.validation.dropped_span_count > 0 && (
            <span className="ml-1 text-amber-600 dark:text-amber-400">
              · {result.validation.dropped_span_count}건은 검증에서 제외됨
            </span>
          )}
        </span>
        <Link
          href={`/results/${result.result_id}`}
          className="font-medium text-sky-700 hover:underline dark:text-sky-400"
        >
          근거 보기 →
        </Link>
      </div>
    </Card>
  );
}
