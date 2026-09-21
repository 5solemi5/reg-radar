"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ActionGradeChip, ApplicabilityChip, Button, Card, SectionTitle, Spinner, StateMessage } from "@/components/ui";
import { api } from "@/lib/api";
import type { ReferenceEvidence } from "@/lib/schemas";
import {
  ACTION_GRADE_META,
  APPLICABILITY_META,
  CHANGE_TYPE_LABEL,
  effectiveDateNote,
  formatDate,
} from "@/lib/display";

export function ResultDetail({ resultId }: { resultId: string }) {
  const result = useQuery({
    queryKey: ["results", resultId],
    queryFn: () => api.getResult(resultId),
  });
  const evidence = useQuery({
    queryKey: ["results", resultId, "evidence"],
    queryFn: () => api.getEvidence(resultId),
  });

  const save = useMutation({
    mutationFn: (note?: string) => api.saveRegulation({ result_id: resultId, note }),
  });
  const feedback = useMutation({
    mutationFn: (helpful: boolean) => api.submitFeedback(resultId, { helpful }),
  });
  const [savedNote, setSavedNote] = useState("");

  if (result.isLoading) return <Spinner label="불러오는 중…" />;

  if (result.error || !result.data) {
    return (
      <StateMessage
        tone="error"
        title="결과를 불러오지 못했습니다"
        description={result.error instanceof Error ? result.error.message : undefined}
        action={<Link href="/dashboard"><Button variant="secondary">대시보드로</Button></Link>}
      />
    );
  }

  const data = result.data;
  const legal = data.legal_evidence;
  const ai = data.ai_interpretation;
  const note = effectiveDateNote(legal.effective_date);

  return (
    <article className="space-y-8">
      <header>
        <Link href="/dashboard" className="text-sm text-slate-500 hover:underline dark:text-slate-400">
          ← 대시보드
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ApplicabilityChip value={data.applicability} />
          {data.action_grade && <ActionGradeChip value={data.action_grade} />}
        </div>
        <h1 className="mt-3 text-2xl font-semibold">
          {legal.law_name} {legal.article_no}
        </h1>
        {legal.article_title && (
          <p className="mt-1 text-lg text-slate-600 dark:text-slate-400">{legal.article_title}</p>
        )}
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          시행 {formatDate(legal.effective_date)}
          {note && <span className="ml-2">({note})</span>}
          {legal.ministry && <span className="ml-2">· {legal.ministry}</span>}
        </p>
        <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
          {APPLICABILITY_META[data.applicability].hint}
          {data.action_grade && ` ${ACTION_GRADE_META[data.action_grade].hint}`}
        </p>
      </header>

      {/* ① 무엇이 바뀌었나 — 법제처가 표시한 변경 구간 (BR-002) */}
      <section>
        <SectionTitle hint="법제처 신구법 비교가 표시한 변경 구간입니다. AI가 만든 것이 아닙니다.">
          무엇이 바뀌었나
        </SectionTitle>
        <Card>
          <p className="text-sm font-medium">
            {CHANGE_TYPE_LABEL[data.change.change_type] ?? data.change.change_type}
          </p>
          {data.change.deletions.length === 0 && data.change.additions.length === 0 && (
            <p className="mt-2 text-sm text-slate-500">표시된 변경 구간이 없습니다.</p>
          )}
          <div className="mt-3 space-y-1.5 font-mono text-sm">
            {data.change.deletions.map((text, i) => (
              <p key={`d${i}`} className="rounded bg-rose-50 px-2 py-1 text-rose-800 dark:bg-rose-950/30 dark:text-rose-300">
                − {text}
              </p>
            ))}
            {data.change.additions.map((text, i) => (
              <p key={`a${i}`} className="rounded bg-emerald-50 px-2 py-1 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
                + {text}
              </p>
            ))}
          </div>
          {data.change.delegation_targets.length > 0 && (
            <p className="mt-3 text-sm text-amber-700 dark:text-amber-400">
              구체적 기준이 {data.change.delegation_targets.join(", ")}에 위임되어 있습니다.
            </p>
          )}
        </Card>
      </section>

      {/* ② 보류라면 무엇이 필요한지 먼저 (FR-008) */}
      {data.applicability === "HOLD" && ai.missing_context.length > 0 && (
        <section>
          <SectionTitle hint="아래 정보를 알면 해당 여부를 확정할 수 있습니다.">
            보류 사유
          </SectionTitle>
          <Card className="border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/20">
            <ul className="list-inside list-disc space-y-1 text-sm text-amber-900 dark:text-amber-300">
              {ai.missing_context.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <Link href="/settings">
              <Button variant="secondary" className="mt-4">
                프로필에 정보 추가하기
              </Button>
            </Link>
          </Card>
        </section>
      )}

      {/* ③ 세 근거를 분리 표시 — 이 화면의 핵심 (AP-05, FR-014) */}
      <section>
        <SectionTitle hint="공식 원문과 AI 해석은 성격이 다릅니다. 섞어서 읽지 않도록 분리해 표시합니다.">
          근거
        </SectionTitle>

        {evidence.isLoading && <Spinner label="근거를 불러오는 중…" />}

        {evidence.data && (
          <div className="space-y-4">
            <EvidenceBlock
              badge="법적 근거"
              badgeClass="bg-slate-900 text-white dark:bg-slate-200 dark:text-slate-900"
              caption="법제처 공식 원문. AI가 생성하지 않은 값입니다."
            >
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-slate-500">법령</dt>
                <dd>{legal.law_name}</dd>
                <dt className="text-slate-500">조문</dt>
                <dd>{legal.article_no}{legal.article_title && ` (${legal.article_title})`}</dd>
                <dt className="text-slate-500">시행일</dt>
                <dd>{formatDate(legal.effective_date)}</dd>
                <dt className="text-slate-500">소관</dt>
                <dd>{legal.ministry ?? "—"}</dd>
              </dl>

              {legal.quoted_spans.length > 0 ? (
                <div className="mt-4">
                  <p className="text-xs font-medium text-slate-500">
                    검증된 원문 인용 — 실제 조문에 존재함을 확인했습니다
                  </p>
                  <div className="mt-2 space-y-2">
                    {legal.quoted_spans.map((span, i) => (
                      <blockquote
                        key={i}
                        className="border-l-2 border-slate-300 pl-3 text-sm text-slate-700 dark:border-slate-600 dark:text-slate-300"
                      >
                        {span}
                      </blockquote>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="mt-4 text-sm text-slate-500">인용된 원문 구절이 없습니다.</p>
              )}

              {data.validation.dropped_span_count > 0 && (
                <p className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                  AI가 제시한 인용 중 {data.validation.dropped_span_count}건은 원문에서
                  확인되지 않아 제외했습니다.
                </p>
              )}

              {legal.source_url && (
                <a
                  href={legal.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-4 inline-block text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
                >
                  법제처에서 원문 보기 ↗
                </a>
              )}
            </EvidenceBlock>

            <EvidenceBlock
              badge="참고 자료"
              badgeClass="bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200"
              caption="정부 가이드·FAQ 등 실무 맥락. 법적 근거와 동일한 권위를 갖지 않습니다."
            >
              {evidence.data.reference_evidence.length === 0 ? (
                <p className="text-sm text-slate-500">
                  관련 참고자료를 찾지 못했습니다. 조문만으로 판단했다는 뜻이며,
                  없는 출처를 지어내지 않습니다.
                </p>
              ) : (
                <ul className="space-y-2">
                  {evidence.data.reference_evidence.map((doc) => (
                    <ReferenceItem key={doc.doc_id} doc={doc} />
                  ))}
                </ul>
              )}
            </EvidenceBlock>

            <EvidenceBlock
              badge="AI 해석"
              badgeClass="bg-sky-600 text-white"
              caption="위 근거 범위 안에서 AI가 해석한 내용입니다. 법적 결론이 아닙니다."
            >
              <p className="text-sm leading-relaxed">{ai.reason}</p>
              {ai.impact_summary && (
                <p className="mt-3 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
                  {ai.impact_summary}
                </p>
              )}
              {ai.affected_work.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-medium text-slate-500">영향을 받는 업무</p>
                  <ul className="mt-1.5 list-inside list-disc text-sm">
                    {ai.affected_work.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              {ai.checklist.length > 0 && (
                <div className="mt-4">
                  <p className="text-xs font-medium text-slate-500">확인할 항목</p>
                  <ul className="mt-1.5 space-y-1 text-sm">
                    {ai.checklist.map((item) => (
                      <li key={item.title} className="flex gap-2">
                        <span aria-hidden className="text-slate-400">☐</span>
                        <span>
                          {item.title}
                          {item.detail && (
                            <span className="block text-xs text-slate-500">{item.detail}</span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="mt-4 text-xs text-slate-500">
                {ai.model && `모델 ${ai.model}`}
                {ai.confidence != null && ` · 확신도 ${Math.round(ai.confidence * 100)}%`}
              </p>
            </EvidenceBlock>

          </div>
        )}
      </section>

      <section className="flex flex-wrap items-center gap-3 border-t border-slate-200 pt-6 dark:border-slate-800">
        <input
          value={savedNote}
          onChange={(e) => setSavedNote(e.target.value)}
          placeholder="메모 (선택)"
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950"
        />
        <Button
          variant="secondary"
          onClick={() => save.mutate(savedNote || undefined)}
          disabled={save.isPending || save.isSuccess}
        >
          {save.isSuccess ? "저장됨" : "저장함에 담기"}
        </Button>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => feedback.mutate(true)} disabled={feedback.isPending}>
            도움됨
          </Button>
          <Button variant="ghost" onClick={() => feedback.mutate(false)} disabled={feedback.isPending}>
            부정확함
          </Button>
        </div>
        {feedback.isSuccess && (
          <span className="text-sm text-emerald-600 dark:text-emerald-400">피드백 감사합니다</span>
        )}
      </section>
    </article>
  );
}

const DOC_TYPE_LABEL: Record<string, string> = {
  INTERPRETATION: "법령해석례",
  GUIDE: "행정규칙",
  CASE: "판례",
  FAQ: "FAQ",
  PRESS: "보도자료",
};

/**
 * 참고자료 1건.
 *
 * 기본은 접어 둔다. 참고자료는 보조 정보인데 본문이 길어 펼쳐 두면 법적 근거보다
 * 화면을 크게 차지한다. 어떤 문서인지(기관·유형·일자)는 접힌 상태에서도 보인다.
 */
function ReferenceItem({ doc }: { doc: ReferenceEvidence }) {
  return (
    <li>
      <details className="group rounded-lg border border-slate-200 dark:border-slate-800">
        <summary className="cursor-pointer list-none p-3 text-sm">
          <span className="font-medium group-open:block">{doc.title ?? doc.source}</span>
          <span className="mt-1 block text-xs text-slate-500">
            {[
              doc.agency,
              DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type,
              doc.published_at,
            ]
              .filter(Boolean)
              .join(" · ")}
            <span className="ml-2 text-slate-400 group-open:hidden">· 펼쳐 보기</span>
          </span>
        </summary>
        <div className="border-t border-slate-200 p-3 text-sm leading-relaxed text-slate-600 dark:border-slate-800 dark:text-slate-400">
          <p className="whitespace-pre-wrap">{doc.snippet}</p>
          <a
            href={doc.source}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-3 inline-block text-xs font-medium text-sky-700 hover:underline dark:text-sky-400"
          >
            법제처에서 원문 보기 ↗
          </a>
        </div>
      </details>
    </li>
  );
}

function EvidenceBlock({
  badge, badgeClass, caption, children,
}: {
  badge: string;
  badgeClass: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <div className="mb-3 flex items-baseline gap-3">
        <span className={`rounded px-2 py-0.5 text-xs font-semibold ${badgeClass}`}>{badge}</span>
        <span className="text-xs text-slate-500 dark:text-slate-400">{caption}</span>
      </div>
      {children}
    </Card>
  );
}
