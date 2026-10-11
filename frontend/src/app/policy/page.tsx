"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";

import { AuthGate } from "@/components/auth-gate";
import { Card, SectionTitle, Spinner, StateMessage } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { AUDIT_ACTION_LABEL, DRAFT_STATE_META } from "@/lib/display";

function PolicyPageContent() {
  const drafts = useQuery({ queryKey: ["policy-drafts"], queryFn: () => api.listPolicyDrafts() });
  const audit = useQuery({ queryKey: ["policy-audit"], queryFn: () => api.getPolicyAudit() });

  if (drafts.isLoading) return <Spinner label="불러오는 중…" />;
  if (drafts.error) {
    const forbidden = drafts.error instanceof ApiError && drafts.error.isPolicyForbidden;
    return (
      <StateMessage
        tone={forbidden ? "neutral" : "error"}
        title={forbidden ? "사내 규정 조직 구성원만 볼 수 있습니다" : "초안을 불러오지 못했습니다"}
        description={forbidden ? "관리자에게 구성원 등록을 요청하세요." : drafts.error.message}
      />
    );
  }

  const list = drafts.data ?? [];
  const waiting = list.filter((d) => d.state === "IN_REVIEW").length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">사내 규정 개정 초안</h1>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          AI가 만든 초안은 확정이 아닙니다. 준법감시인이 승인해야 하며, 제출한 사람은 자기 초안을 승인할
          수 없습니다. 검토 대기 {waiting}건.
        </p>
      </div>

      {list.length === 0 ? (
        <StateMessage
          title="아직 초안이 없습니다"
          description="분석 결과 상세 화면의 ‘사내 규정 영향’에서 개정 초안을 만들 수 있습니다."
        />
      ) : (
        <ul className="space-y-3">
          {list.map((d) => {
            const meta = DRAFT_STATE_META[d.state];
            return (
              <li key={d.draft_id}>
                <Link href={`/policy/${d.draft_id}`}>
                  <Card className="flex flex-wrap items-center gap-3 hover:border-slate-400">
                    <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", meta.chip)}>
                      {meta.label}
                    </span>
                    <span className="font-medium">{d.policy_ref}</span>
                    <span className="text-sm text-slate-500">← {d.law_ref}</span>
                    {d.issues.length > 0 && (
                      <span className="ml-auto text-xs text-amber-700 dark:text-amber-400">
                        검증 문제 {d.issues.length}건
                      </span>
                    )}
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <section>
        <SectionTitle hint="추가만 되는 기록입니다. 각 기록이 직전 기록의 해시를 품어, 중간을 고치거나 지우면 끊긴 위치가 드러납니다.">
          감사 로그
        </SectionTitle>
        {audit.data && (
          <Card>
            <p
              data-testid="audit-integrity"
              className={clsx(
                "text-sm font-medium",
                audit.data.intact ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400",
              )}
            >
              {audit.data.intact
                ? `체인 검증 통과 · ${audit.data.events.length}건`
                : `체인이 ${audit.data.broken_at}번째 기록에서 끊겼습니다`}
            </p>
            <ol className="mt-3 space-y-1 text-sm">
              {[...audit.data.events].reverse().slice(0, 30).map((e) => (
                <li key={e.seq} className="flex flex-wrap gap-x-3 text-slate-600 dark:text-slate-400">
                  <span className="font-mono text-xs text-slate-400">#{e.seq}</span>
                  <span>{new Date(e.at).toLocaleString("ko-KR")}</span>
                  <span className="font-medium text-slate-800 dark:text-slate-200">
                    {AUDIT_ACTION_LABEL[e.action] ?? e.action}
                  </span>
                  <span>{e.actor} ({e.role === "COMPLIANCE_OFFICER" ? "준법감시인" : "현업"})</span>
                  <span className="font-mono text-xs text-slate-400" title={e.hash}>
                    {e.hash.slice(0, 10)}
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>
    </div>
  );
}

export default function PolicyPage() {
  return (
    <AuthGate>
      <PolicyPageContent />
    </AuthGate>
  );
}
