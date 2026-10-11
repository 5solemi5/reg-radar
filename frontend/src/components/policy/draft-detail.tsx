"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";

import { AuthGate } from "@/components/auth-gate";
import { Button, Card, SectionTitle, Spinner, StateMessage } from "@/components/ui";
import { api } from "@/lib/api";
import { AUDIT_ACTION_LABEL, DRAFT_STATE_META, wordDiff } from "@/lib/display";
import type { PolicyDraft } from "@/lib/schemas";

/**
 * 개정 초안 상세 — 현행과 개정안을 나란히, 바뀐 어절을 표시한다.
 *
 * 버튼은 상태에 맞는 것만 보인다. 권한(준법감시인·4-eyes)은 서버가 판단하고, 막히면
 * 서버가 준 사유를 그대로 보여준다 — 화면이 권한을 추측하면 서버와 어긋난다.
 */
export function PolicyDraftDetail({ draftId }: { draftId: string }) {
  return (
    <AuthGate>
      <DraftDetailContent draftId={draftId} />
    </AuthGate>
  );
}

function DraftDetailContent({ draftId }: { draftId: string }) {
  const queryClient = useQueryClient();
  const draft = useQuery({
    queryKey: ["policy-draft", draftId],
    queryFn: () => api.getPolicyDraft(draftId),
  });
  const audit = useQuery({ queryKey: ["policy-audit"], queryFn: () => api.getPolicyAudit() });

  const refresh = (d: PolicyDraft) => {
    queryClient.setQueryData(["policy-draft", draftId], d);
    queryClient.invalidateQueries({ queryKey: ["policy-drafts"] });
    queryClient.invalidateQueries({ queryKey: ["policy-audit"] });
  };
  const act = useMutation({
    mutationFn: (fn: () => Promise<PolicyDraft>) => fn(),
    onSuccess: refresh,
  });

  const [ack, setAck] = useState(false);
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState<string | null>(null);

  if (draft.isLoading) return <Spinner label="불러오는 중…" />;
  if (draft.error || !draft.data) {
    return (
      <StateMessage
        tone="error"
        title="초안을 찾을 수 없습니다"
        description={draft.error?.message}
        action={<Link href="/policy" className="text-sm underline">목록으로</Link>}
      />
    );
  }

  const d = draft.data;
  const meta = DRAFT_STATE_META[d.state];
  const events = (audit.data?.events ?? []).filter((e) => e.draft_id === d.draft_id);

  return (
    <div className="space-y-8">
      <div>
        <Link href="/policy" className="text-sm text-slate-500 hover:underline">← 초안 목록</Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <span className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", meta.chip)} data-testid="draft-state">
            {meta.label}
          </span>
          <h1 className="text-2xl font-semibold">{d.policy_ref}</h1>
        </div>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
          근거 법령 {d.law_ref} · {d.relation === "CONFLICT" ? "법과 어긋남" : "보완 필요"} · 작성 {d.created_by}
          {d.submitted_by && ` · 제출 ${d.submitted_by}`}
          {d.decided_by && ` · 결정 ${d.decided_by}`}
        </p>
      </div>

      {d.issues.length > 0 && (
        <Card className="border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/20">
          <p className="text-sm font-medium text-amber-900 dark:text-amber-300">
            검증 문제 {d.issues.length}건 — 승인하려면 확인 표시가 필요합니다
          </p>
          <ul className="mt-2 list-disc pl-5 text-sm text-amber-900 dark:text-amber-300">
            {d.issues.map((issue) => <li key={issue}>{issue}</li>)}
          </ul>
        </Card>
      )}

      <section>
        <SectionTitle hint="빨간 줄은 지워지는 말, 초록은 새로 들어가는 말입니다.">현행과 개정안</SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <p className="mb-2 text-xs font-semibold text-slate-500">현행</p>
            <p className="text-sm leading-7 whitespace-pre-wrap">{d.current_text}</p>
          </Card>
          <Card>
            <p className="mb-2 text-xs font-semibold text-slate-500">개정안 (변경 표시)</p>
            {editing !== null ? (
              <textarea
                value={editing}
                onChange={(e) => setEditing(e.target.value)}
                rows={8}
                className="w-full rounded-lg border border-slate-300 p-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              />
            ) : (
              <p className="text-sm leading-7 whitespace-pre-wrap" data-testid="draft-diff">
                {wordDiff(d.current_text, d.proposed_text).map((part, i) =>
                  part.kind === "same" ? (
                    <span key={i}>{part.text}</span>
                  ) : part.kind === "added" ? (
                    <ins key={i} className="bg-emerald-100 no-underline text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300">
                      {part.text}
                    </ins>
                  ) : (
                    <del key={i} className="bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300">
                      {part.text}
                    </del>
                  ),
                )}
              </p>
            )}
          </Card>
        </div>
      </section>

      <section className="space-y-3">
        <SectionTitle hint="권한은 서버가 판단합니다. 막히면 그 사유를 그대로 보여드립니다.">처리</SectionTitle>
        <div className="flex flex-wrap items-center gap-3">
          {d.state === "DRAFTED" && (
            <Button onClick={() => act.mutate(() => api.submitPolicyDraft(d.draft_id))} disabled={act.isPending}>
              검토 요청
            </Button>
          )}
          {d.state === "IN_REVIEW" && (
            <>
              {d.issues.length > 0 && (
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  검증 문제를 확인했습니다
                </label>
              )}
              <Button
                onClick={() => act.mutate(() => api.approvePolicyDraft(d.draft_id, ack))}
                disabled={act.isPending}
              >
                승인
              </Button>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="반려 사유"
                className="min-w-48 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
              />
              <Button
                variant="secondary"
                onClick={() => act.mutate(() => api.rejectPolicyDraft(d.draft_id, reason))}
                disabled={act.isPending || !reason.trim()}
              >
                반려
              </Button>
            </>
          )}
          {d.state === "REJECTED" &&
            (editing === null ? (
              <Button variant="secondary" onClick={() => setEditing(d.proposed_text)}>개정안 고치기</Button>
            ) : (
              <>
                <Button
                  onClick={() =>
                    act.mutate(async () => {
                      const r = await api.revisePolicyDraft(d.draft_id, editing);
                      setEditing(null);
                      return r;
                    })
                  }
                  disabled={act.isPending || !editing.trim()}
                >
                  고친 안 저장
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)}>취소</Button>
              </>
            ))}
        </div>
        {act.error && (
          <p role="alert" data-testid="action-error" className="text-sm text-rose-700 dark:text-rose-400">
            {act.error.message}
          </p>
        )}
      </section>

      <section>
        <SectionTitle>의견</SectionTitle>
        <ul className="space-y-2 text-sm">
          {d.comments.map((c, i) => (
            <li key={i}><span className="font-medium">{c.user_id}</span> {c.text}</li>
          ))}
        </ul>
        <div className="mt-3 flex gap-2">
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="의견 남기기"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          />
          <Button
            variant="secondary"
            disabled={!comment.trim() || act.isPending}
            onClick={() =>
              act.mutate(async () => {
                const r = await api.commentPolicyDraft(d.draft_id, comment);
                setComment("");
                return r;
              })
            }
          >
            남기기
          </Button>
        </div>
      </section>

      <section>
        <SectionTitle>이 초안의 감사 기록</SectionTitle>
        <ol className="space-y-1 text-sm text-slate-600 dark:text-slate-400">
          {events.map((e) => (
            <li key={e.seq} className="flex flex-wrap gap-x-3">
              <span>{new Date(e.at).toLocaleString("ko-KR")}</span>
              <span className="font-medium text-slate-800 dark:text-slate-200">
                {AUDIT_ACTION_LABEL[e.action] ?? e.action}
              </span>
              <span>{e.actor}</span>
              {e.before !== e.after && e.after && <span>{e.before ?? "—"} → {e.after}</span>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
