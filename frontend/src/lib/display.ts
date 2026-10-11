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

// ── 사내 규정 영향·개정 초안 ─────────────────────────────────────────

export const FINDING_STATUS_META: Record<
  "ACTIONABLE" | "NEEDS_REVIEW" | "NO_ACTION",
  { label: string; chip: string; hint: string }
> = {
  ACTIONABLE: {
    label: "개정 대상",
    chip: "bg-rose-50 text-rose-800 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:ring-rose-900",
    hint: "법령과 사내 규정 양쪽 원문 근거가 확인됐고, 반론 검토도 통과했습니다.",
  },
  NEEDS_REVIEW: {
    label: "사람 검토",
    chip: "bg-amber-50 text-amber-900 ring-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:ring-amber-900",
    hint: "근거가 부족하거나 반론 검토가 이겼습니다. 자동으로 버리지 않고 사람에게 넘깁니다.",
  },
  NO_ACTION: {
    label: "조치 불필요",
    chip: "bg-slate-50 text-slate-600 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
    hint: "부합하거나 관련이 없습니다.",
  },
};

export const DRAFT_STATE_META: Record<
  "DRAFTED" | "IN_REVIEW" | "APPROVED" | "REJECTED",
  { label: string; chip: string }
> = {
  DRAFTED: { label: "초안", chip: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  IN_REVIEW: { label: "검토 중", chip: "bg-sky-100 text-sky-800 dark:bg-sky-950/50 dark:text-sky-300" },
  APPROVED: { label: "승인", chip: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" },
  REJECTED: { label: "반려", chip: "bg-rose-100 text-rose-800 dark:bg-rose-950/50 dark:text-rose-300" },
};

export const AUDIT_ACTION_LABEL: Record<string, string> = {
  create: "초안 생성",
  submit: "검토 요청",
  approve: "승인",
  reject: "반려",
  revise: "수정",
  comment: "의견",
};

/**
 * 어절 단위 비교 (LCS). 현행 조문과 개정안의 차이를 표시한다.
 * 조문은 수백 자라 O(n·m)으로 충분하다.
 */
export type DiffPart = { kind: "same" | "added" | "removed"; text: string };

export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  const dp: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("removed", a[i++]);
    } else {
      push("added", b[j++]);
    }
  }
  while (i < a.length) push("removed", a[i++]);
  while (j < b.length) push("added", b[j++]);
  return out;
}
