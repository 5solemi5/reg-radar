/**
 * 판정·행동등급의 표시 규칙 (03 요구사항 §5-2).
 *
 * 색과 문구를 한 곳에서 정의한다. 화면마다 다르게 쓰면 사용자가 같은 상태를
 * 다른 것으로 오해한다.
 */
import type { ActionGrade, Applicability, AnalysisStatus } from "./schemas";

export const APPLICABILITY_META: Record<
  Applicability,
  { label: string; hint: string; dot: string; chip: string }
> = {
  APPLICABLE: {
    label: "해당",
    hint: "내 프로필과 적용 조건이 연결되었습니다.",
    dot: "bg-rose-500",
    chip: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-900",
  },
  HOLD: {
    label: "보류",
    hint: "확정하려면 추가 정보가 필요합니다.",
    dot: "bg-amber-500",
    chip: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900",
  },
  NOT_APPLICABLE: {
    label: "무관",
    hint: "현재 프로필 기준으로 직접 적용되지 않습니다.",
    dot: "bg-slate-400",
    chip: "bg-slate-100 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
  },
};

export const ACTION_GRADE_META: Record<
  ActionGrade,
  { label: string; hint: string; chip: string }
> = {
  ACTION: {
    label: "조치 필요",
    hint: "기한 내 구체적인 조치가 필요합니다.",
    chip: "bg-rose-600 text-white",
  },
  DECISION: {
    label: "방침 결정",
    hint: "회사 기준을 다시 정해야 하는 변화입니다.",
    chip: "bg-orange-500 text-white",
  },
  AWARENESS: {
    label: "인지",
    hint: "지금 할 일은 없고 알고만 있으면 됩니다.",
    chip: "bg-sky-600 text-white",
  },
};

export const ANALYSIS_STATUS_META: Record<
  AnalysisStatus,
  { label: string; tone: string }
> = {
  CREATED: { label: "대기 중", tone: "text-slate-500" },
  RUNNING: { label: "분석 중", tone: "text-sky-600 dark:text-sky-400" },
  COMPLETED: { label: "완료", tone: "text-emerald-600 dark:text-emerald-400" },
  FAILED: { label: "실패", tone: "text-rose-600 dark:text-rose-400" },
};

export const COMPANY_SIZE_OPTIONS = [
  { value: "SOLO", label: "1인 사업자" },
  { value: "MICRO", label: "5인 미만" },
  { value: "SMALL", label: "5~49인" },
  { value: "MEDIUM", label: "50~299인" },
  { value: "LARGE", label: "300인 이상" },
] as const;

export const CHANGE_TYPE_LABEL: Record<string, string> = {
  NEW: "신설",
  AMENDED: "개정",
  DELETED: "삭제",
  UNCHANGED: "변경 없음",
};

export function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(date);
}

export function formatDateTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/** 시행일까지 남은 일수. 음수면 이미 시행된 것. */
export function daysUntil(dateString: string | null): number | null {
  if (!dateString) return null;
  const target = new Date(dateString);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function effectiveDateNote(dateString: string | null): string | null {
  const days = daysUntil(dateString);
  if (days === null) return null;
  if (days > 0) return `시행까지 ${days}일`;
  if (days === 0) return "오늘 시행";
  return `${Math.abs(days)}일 전 시행됨`;
}
