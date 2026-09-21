"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, Spinner, StateMessage } from "@/components/ui";
import { api } from "@/lib/api";
import { COMPANY_SIZE_OPTIONS } from "@/lib/display";
import {
  ProfileInput,
  type ActivityAnswer,
  type ActivityAnswers,
  type CompanySize,
  type Profile,
} from "@/lib/schemas";

/**
 * '아니오'와 '모름'을 따로 둔다.
 *
 * 체크박스 하나로 받으면 체크하지 않은 것이 '아니오'인지 '아직 답하지 않음'인지
 * 알 수 없다. 그러면 질문을 건너뛴 사용자에게 '무관'이라고 단정하게 된다.
 */
const ANSWER_OPTIONS: { value: ActivityAnswer; label: string }[] = [
  { value: "YES", label: "예" },
  { value: "NO", label: "아니오" },
  { value: "UNKNOWN", label: "모름" },
];

const INTEREST_OPTIONS = [
  "노동·인사", "개인정보", "안전·보건", "세무·회계",
  "전자상거래", "환경", "식품·위생", "금융",
];

type Props = {
  initial?: Profile | null;
  submitLabel: string;
  pending: boolean;
  errorMessage?: string | null;
  onSubmit: (input: ProfileInput) => void;
};

export function ProfileForm({
  initial, submitLabel, pending, errorMessage, onSubmit,
}: Props) {
  const [job, setJob] = useState(initial?.job ?? "");
  const [industry, setIndustry] = useState(initial?.industry ?? "");
  const [companySize, setCompanySize] = useState<CompanySize>(
    initial?.company_size ?? "SMALL",
  );
  const [employeeCount, setEmployeeCount] = useState(
    initial?.employee_count != null ? String(initial.employee_count) : "",
  );
  const [interests, setInterests] = useState<string[]>(initial?.interests ?? []);
  const [activities, setActivities] = useState<ActivityAnswers>(
    initial?.activities ?? {},
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  // 질문 문구는 백엔드가 준다. 여기에 복제해 두면 반드시 어긋난다 (ADR-033).
  const questions = useQuery({
    queryKey: ["activity-questions"],
    queryFn: () => api.getActivityQuestions(),
    staleTime: Infinity,
  });

  function toggleInterest(value: string) {
    setInterests((prev) =>
      prev.includes(value) ? prev.filter((i) => i !== value) : [...prev, value],
    );
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const candidate = {
      job: job.trim(),
      industry: industry.trim(),
      company_size: companySize,
      employee_count: employeeCount.trim() === "" ? null : Number(employeeCount),
      interests,
      activities,
    };
    const parsed = ProfileInput.safeParse(candidate);
    if (!parsed.success) {
      const next: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        next[String(issue.path[0])] = issue.message;
      }
      setErrors(next);
      return;
    }
    setErrors({});
    onSubmit(parsed.data);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <Card className="space-y-5">
        <Field
          label="직무"
          hint="무슨 일을 하시나요? 구체적일수록 관련성 판단이 정확해집니다."
          error={errors.job}
        >
          <input
            value={job}
            onChange={(e) => setJob(e.target.value)}
            placeholder="예: HR 담당자 (채용·근태·취업규칙)"
            className={inputClass}
            aria-invalid={Boolean(errors.job)}
          />
        </Field>

        <Field label="업종" error={errors.industry}>
          <input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            placeholder="예: IT 서비스, 이커머스 소매, 제조"
            className={inputClass}
            aria-invalid={Boolean(errors.industry)}
          />
        </Field>

        <Field label="회사 규모" error={errors.company_size}>
          <select
            value={companySize}
            onChange={(e) => setCompanySize(e.target.value as CompanySize)}
            className={inputClass}
          >
            {COMPANY_SIZE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field
          label="상시근로자 수 (선택)"
          hint="많은 법령이 '상시 N명 이상'을 기준으로 적용됩니다. 비워두면 그런 조문은 보류로 나옵니다."
          error={errors.employee_count}
        >
          <input
            type="number"
            min={0}
            value={employeeCount}
            onChange={(e) => setEmployeeCount(e.target.value)}
            placeholder="예: 80"
            className={inputClass}
          />
        </Field>

        <Field label="관심 규제 영역 (선택)">
          <div className="flex flex-wrap gap-2">
            {INTEREST_OPTIONS.map((option) => {
              const active = interests.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  onClick={() => toggleInterest(option)}
                  aria-pressed={active}
                  className={
                    "rounded-full border px-3 py-1.5 text-sm transition " +
                    (active
                      ? "border-slate-900 bg-slate-900 text-white dark:border-sky-500 dark:bg-sky-600"
                      : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800")
                  }
                >
                  {option}
                </button>
              );
            })}
          </div>
        </Field>
      </Card>

      <Card className="space-y-4">
        <div>
          <h2 className="text-sm font-medium">사업 활동</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            업종만으로는 알 수 없지만 법령 적용을 가르는 사실들입니다. 답해 주실수록
            보류가 줄고 확정 판정이 늘어납니다.{" "}
            <strong className="font-medium">모르면 &lsquo;모름&rsquo;으로 두셔도 됩니다</strong> —
            그 조문은 보류로 나옵니다.
          </p>
        </div>

        {questions.isLoading && <Spinner label="질문을 불러오는 중…" />}

        {questions.isError && (
          <StateMessage
            tone="info"
            title="사업 활동 질문을 불러오지 못했습니다"
            description="이 항목 없이도 저장할 수 있습니다. 나중에 설정에서 다시 채울 수 있습니다."
          />
        )}

        {questions.data?.items.map((q) => (
          <div key={q.activity} className="border-t border-slate-200 pt-4 dark:border-slate-800">
            {/* 질문을 legend·문단·aria-label로 세 번 적으면 스크린리더가 세 번 읽는다.
                한 번만 쓰고 radiogroup이 그것을 가리킨다. */}
            <p id={`activity-q-${q.activity}`} className="text-sm">
              {q.question}
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{q.hint}</p>
            <div
              className="mt-2 flex gap-2"
              role="radiogroup"
              aria-labelledby={`activity-q-${q.activity}`}
            >
              {ANSWER_OPTIONS.map((option) => {
                const current = activities[q.activity] ?? "UNKNOWN";
                const active = current === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    data-testid={`activity-${q.activity}-${option.value}`}
                    onClick={() =>
                      setActivities((prev) => ({ ...prev, [q.activity]: option.value }))
                    }
                    className={
                      "rounded-full border px-3 py-1 text-sm transition " +
                      (active
                        ? "border-slate-900 bg-slate-900 text-white dark:border-sky-500 dark:bg-sky-600"
                        : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800")
                    }
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </Card>

      {errorMessage && <StateMessage tone="error" title="저장하지 못했습니다" description={errorMessage} />}

      <div className="flex justify-end">
        <Button type="submit" disabled={pending}>
          {pending ? "저장 중…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}

const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm " +
  "placeholder:text-slate-400 focus:border-slate-900 focus:outline-none " +
  "dark:border-slate-700 dark:bg-slate-950 dark:focus:border-sky-500";

function Field({
  label, hint, error, children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      {hint && <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{hint}</span>}
      <div className="mt-2">{children}</div>
      {error && <span className="mt-1.5 block text-xs text-rose-600 dark:text-rose-400">{error}</span>}
    </label>
  );
}
