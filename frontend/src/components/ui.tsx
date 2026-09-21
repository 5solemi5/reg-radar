import clsx from "clsx";

import {
  ACTION_GRADE_META,
  APPLICABILITY_META,
} from "@/lib/display";
import type { ActionGrade, Applicability } from "@/lib/schemas";

export function ApplicabilityChip({ value }: { value: Applicability }) {
  const meta = APPLICABILITY_META[value];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        meta.chip,
      )}
      title={meta.hint}
    >
      <span className={clsx("size-1.5 rounded-full", meta.dot)} aria-hidden />
      {meta.label}
    </span>
  );
}

export function ActionGradeChip({ value }: { value: ActionGrade }) {
  const meta = ACTION_GRADE_META[value];
  return (
    <span
      className={clsx("rounded-full px-2.5 py-1 text-xs font-semibold", meta.chip)}
      title={meta.hint}
    >
      {meta.label}
    </span>
  );
}

export function Card({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Button({
  variant = "primary",
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
}) {
  return (
    <button
      {...props}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium",
        "transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600",
        "disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" &&
          "bg-slate-900 text-white hover:bg-slate-700 dark:bg-sky-600 dark:hover:bg-sky-500",
        variant === "secondary" &&
          "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800",
        variant === "ghost" &&
          "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
        className,
      )}
    />
  );
}

/** 로딩·빈 상태·에러를 빈 화면으로 두지 않는다 (NFR-013). */
export function StateMessage({
  title,
  description,
  action,
  tone = "neutral",
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  tone?: "neutral" | "error";
}) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-dashed p-8 text-center",
        tone === "error"
          ? "border-rose-300 bg-rose-50/60 dark:border-rose-900 dark:bg-rose-950/20"
          : "border-slate-300 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-900/40",
      )}
      role={tone === "error" ? "alert" : undefined}
    >
      <p
        className={clsx(
          "font-medium",
          tone === "error"
            ? "text-rose-800 dark:text-rose-300"
            : "text-slate-800 dark:text-slate-200",
        )}
      >
        {title}
      </p>
      {description && (
        <div className="mt-2 text-sm text-slate-600 dark:text-slate-400">{description}</div>
      )}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
      <span
        className="size-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700 dark:border-slate-700 dark:border-t-slate-200"
        aria-hidden
      />
      <span role="status">{label}</span>
    </span>
  );
}

export function SectionTitle({
  children,
  hint,
}: {
  children: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-semibold tracking-wide text-slate-900 uppercase dark:text-slate-100">
        {children}
      </h2>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
