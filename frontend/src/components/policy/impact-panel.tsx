"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";

import { Button, Card, Spinner, StateMessage } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { FINDING_STATUS_META } from "@/lib/display";
import type { PolicyFinding } from "@/lib/schemas";

/**
 * 결과 상세 화면의 '사내 규정 영향' 패널 (문서 12 §4).
 *
 * 이 조문이 닿는 사내 규정 조항을 찾고, 개정이 필요한 조항은 초안을 만든다.
 * Agent는 규정을 고치지 않는다 — 초안을 내고, 승인은 준법감시인이 한다.
 * 조직 구성원이 아니면 패널 대신 안내만 보인다.
 */
export function PolicyImpactPanel({ lawId, articleNo }: { lawId: string; articleNo: string }) {
  const queryClient = useQueryClient();
  const impact = useMutation({
    mutationFn: () => api.assessPolicyImpact({ law_id: lawId, article_no: articleNo }),
  });
  const draft = useMutation({
    mutationFn: (policyRef: string) =>
      api.createPolicyDraft({ law_id: lawId, article_no: articleNo, policy_ref: policyRef }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["policy-drafts"] }),
  });

  if (!impact.data && !impact.isPending && !impact.error) {
    return (
      <Card>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          이 조문이 사내 규정 어느 조항에 닿는지 찾고, 개정이 필요한 조항은 초안을 만듭니다.
          초안은 준법감시인이 승인해야 효력이 있습니다.
        </p>
        <Button className="mt-3" onClick={() => impact.mutate()}>
          사내 규정 영향 분석
        </Button>
      </Card>
    );
  }

  if (impact.isPending) return <Spinner label="사내 규정 후보를 찾고 영향을 판단하는 중…" />;

  if (impact.error) {
    const err = impact.error;
    if (err instanceof ApiError && err.isPolicyForbidden) {
      return (
        <StateMessage
          title="사내 규정 조직 구성원만 볼 수 있습니다"
          description="관리자에게 구성원 등록(STAFF 또는 COMPLIANCE_OFFICER)을 요청하세요."
        />
      );
    }
    return (
      <StateMessage
        tone="error"
        title="영향 분석에 실패했습니다"
        description={err.message}
        action={<Button variant="secondary" onClick={() => impact.mutate()}>다시 시도</Button>}
      />
    );
  }

  const data = impact.data!;
  const order = { ACTIONABLE: 0, NEEDS_REVIEW: 1, NO_ACTION: 2 } as const;
  const findings = [...data.findings].sort((x, y) => order[x.status] - order[y.status]);

  return (
    <div className="space-y-3" data-testid="policy-impact">
      <p className="text-xs text-slate-500 dark:text-slate-400">{data.corpus_label}</p>
      {findings.map((f) => (
        <FindingCard
          key={f.policy_ref}
          finding={f}
          drafting={draft.isPending && draft.variables === f.policy_ref}
          onDraft={() => draft.mutate(f.policy_ref)}
          createdId={draft.data?.policy_ref === f.policy_ref ? draft.data.draft_id : undefined}
        />
      ))}
      {draft.error && (
        <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">
          {draft.error.message}
        </p>
      )}
    </div>
  );
}

function FindingCard({
  finding: f,
  drafting,
  onDraft,
  createdId,
}: {
  finding: PolicyFinding;
  drafting: boolean;
  onDraft: () => void;
  createdId?: string;
}) {
  const meta = FINDING_STATUS_META[f.status];
  const canDraft = f.relation === "CONFLICT" || f.relation === "UPDATE_RECOMMENDED";
  return (
    <Card className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={clsx("rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset", meta.chip)}
          title={meta.hint}
        >
          {meta.label}
        </span>
        <span className="font-medium">{f.policy_ref}</span>
        {f.relation && <span className="text-xs text-slate-500">{f.relation}</span>}
      </div>
      {f.status !== "NO_ACTION" && (
        <>
          <p className="text-sm text-slate-700 dark:text-slate-300">{f.reason}</p>
          {f.law_spans.length > 0 && (
            <blockquote className="border-l-2 border-sky-400 pl-3 text-sm text-slate-600 dark:text-slate-400">
              <span className="mr-1 text-xs font-semibold text-sky-700 dark:text-sky-400">법령 원문</span>
              {f.law_spans.join(" … ")}
            </blockquote>
          )}
          {f.policy_spans.length > 0 && (
            <blockquote className="border-l-2 border-slate-400 pl-3 text-sm text-slate-600 dark:text-slate-400">
              <span className="mr-1 text-xs font-semibold">사내 규정 원문</span>
              {f.policy_spans.join(" … ")}
            </blockquote>
          )}
          {f.issues.length > 0 && (
            <ul className="list-disc pl-5 text-xs text-amber-800 dark:text-amber-300">
              {f.issues.map((issue) => <li key={issue}>{issue}</li>)}
            </ul>
          )}
          {f.missing_context.length > 0 && (
            <p className="text-xs text-slate-500">확인 필요: {f.missing_context.join(", ")}</p>
          )}
          {canDraft &&
            (createdId ? (
              <Link href={`/policy/${createdId}`} className="text-sm font-medium text-sky-700 hover:underline dark:text-sky-400">
                만든 초안 보기 →
              </Link>
            ) : (
              <Button variant="secondary" onClick={onDraft} disabled={drafting}>
                {drafting ? "초안 작성 중…" : "개정 초안 만들기"}
              </Button>
            ))}
        </>
      )}
    </Card>
  );
}
