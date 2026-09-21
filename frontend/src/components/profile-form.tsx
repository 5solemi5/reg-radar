"use client";

import { useState } from "react";

import { Button, Card, StateMessage } from "@/components/ui";
import { COMPANY_SIZE_OPTIONS } from "@/lib/display";
import { ProfileInput, type CompanySize, type Profile } from "@/lib/schemas";

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
  const [errors, setErrors] = useState<Record<string, string>>({});

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
