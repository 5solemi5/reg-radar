"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card } from "@/components/ui";
import { ApplicabilityChip } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { AiInterpretation, ReassessResult } from "@/lib/schemas";

/**
 * 보류 해소 폼 (FR-008).
 *
 * 보류는 "무엇을 알면 확정할 수 있는지"를 이미 말하고 있다. 사용자가 설정
 * 화면까지 가서 프로필을 고치고 분석을 처음부터 다시 돌리게 만들 이유가 없다.
 * 여기서 값을 받아 **그 조문만** 다시 판단한다.
 */
export function ReassessForm({
  resultId,
  ai,
}: {
  resultId: string;
  ai: AiInterpretation;
}) {
  const queryClient = useQueryClient();
  const [employeeCount, setEmployeeCount] = useState("");
  const [notes, setNotes] = useState("");
  const [applyToProfile, setApplyToProfile] = useState(true);
  const [outcome, setOutcome] = useState<ReassessResult | null>(null);

  // 상시근로자 수를 묻는 보류인지. 그렇다면 숫자 입력을 앞세운다.
  const asksHeadcount = ai.missing_context.some((m) => /근로자|인원|규모/.test(m));

  const reassess = useMutation({
    mutationFn: () =>
      api.reassess(resultId, {
        employee_count: employeeCount.trim() ? Number(employeeCount) : undefined,
        notes: notes.trim() || undefined,
        apply_to_profile: applyToProfile,
      }),
    onSuccess: (data) => {
      setOutcome(data);
      // 새 결과가 생겼으므로 목록과 프로필을 다시 읽는다.
      queryClient.invalidateQueries({ queryKey: ["analyses"] });
      queryClient.invalidateQueries({ queryKey: ["profile"] });
    },
  });

  const canSubmit = Boolean(employeeCount.trim() || notes.trim());

  if (outcome) {
    return (
      <Card
        className={
          outcome.changed
            ? "border-emerald-300 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/20"
            : "border-slate-300 bg-slate-50 dark:border-slate-700 dark:bg-slate-900"
        }
      >
        <p className="text-sm font-medium">{outcome.message}</p>

        <div className="mt-3 flex items-center gap-2 text-sm">
          <ApplicabilityChip value={outcome.previous_applicability} />
          <span aria-hidden className="text-slate-400">
            →
          </span>
          <ApplicabilityChip value={outcome.new_applicability} />
        </div>

        <p className="mt-3 text-sm leading-relaxed text-slate-700 dark:text-slate-300">
          {outcome.result.ai_interpretation.reason}
        </p>

        <div className="mt-4 rounded-lg bg-white/70 p-3 text-xs dark:bg-slate-900/50">
          <p className="font-medium text-slate-600 dark:text-slate-400">
            반영한 정보
          </p>
          <ul className="mt-1 space-y-0.5 text-slate-600 dark:text-slate-400">
            {Object.entries(outcome.added_context).map(([key, value]) => (
              <li key={key}>
                {key}: {value}
              </li>
            ))}
          </ul>
        </div>

        <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
          이전 판정은 그대로 보존됩니다. 무엇을 채워 판정이 어떻게 바뀌었는지
          이력에 남습니다.
        </p>

        <a
          href={`/results/${outcome.result.result_id}`}
          className="mt-3 inline-block text-sm font-medium text-sky-700 hover:underline dark:text-sky-400"
        >
          새 판정 결과 보기 →
        </a>
      </Card>
    );
  }

  return (
    <Card className="border-amber-300 bg-amber-50/60 dark:border-amber-900 dark:bg-amber-950/20">
      <p className="text-sm font-medium text-amber-900 dark:text-amber-300">
        이 정보가 있으면 확정할 수 있습니다
      </p>
      <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-sm text-amber-800 dark:text-amber-400">
        {ai.missing_context.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>

      <div className="mt-4 space-y-3">
        {asksHeadcount && (
          <label className="block">
            <span className="text-sm font-medium">상시근로자 수</span>
            <input
              type="number"
              min={0}
              value={employeeCount}
              onChange={(e) => setEmployeeCount(e.target.value)}
              placeholder="예: 80"
              className={inputClass}
            />
          </label>
        )}

        <label className="block">
          <span className="text-sm font-medium">
            추가 설명 {asksHeadcount && "(선택)"}
          </span>
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="판단에 필요한 다른 정보가 있다면 적어 주세요"
            className={inputClass}
          />
        </label>

        {asksHeadcount && employeeCount.trim() && (
          <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
            <input
              type="checkbox"
              checked={applyToProfile}
              onChange={(e) => setApplyToProfile(e.target.checked)}
              className="size-4"
            />
            프로필에도 저장해서 다음 분석부터 반영하기
          </label>
        )}
      </div>

      {reassess.error && (
        <p role="alert" className="mt-3 text-sm text-rose-700 dark:text-rose-400">
          {reassess.error instanceof ApiError
            ? reassess.error.message
            : "다시 판단하지 못했습니다."}
        </p>
      )}

      <Button
        onClick={() => reassess.mutate()}
        disabled={!canSubmit || reassess.isPending}
        className="mt-4"
      >
        {reassess.isPending ? "다시 판단하는 중…" : "이 정보로 다시 판단하기"}
      </Button>

      <p className="mt-2 text-xs text-amber-800/80 dark:text-amber-400/80">
        이 조문만 다시 판단합니다. 분석 전체를 다시 돌리지 않습니다.
      </p>
    </Card>
  );
}

const inputClass =
  "mt-2 w-full rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm " +
  "placeholder:text-slate-400 focus:border-amber-500 focus:outline-none " +
  "dark:border-amber-900 dark:bg-slate-950";
