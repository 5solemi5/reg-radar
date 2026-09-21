/**
 * 백엔드 응답 스키마 (docs/05_API_명세서.md 기준).
 *
 * 서버를 믿고 `as` 캐스팅하는 대신 런타임에 검증한다. 백엔드 계약이 바뀌면
 * 화면이 undefined로 조용히 깨지는 대신 어디서 어긋났는지 즉시 드러난다.
 *
 * AP-05: 법적 근거 / 참고자료 / AI 해석을 별도 타입으로 유지한다.
 * 프론트에서도 이 셋을 섞으려면 의도적으로 합쳐야 한다.
 */
import { z } from "zod";

export const Applicability = z.enum(["APPLICABLE", "HOLD", "NOT_APPLICABLE"]);
export type Applicability = z.infer<typeof Applicability>;

export const ActionGrade = z.enum(["ACTION", "DECISION", "AWARENESS"]);
export type ActionGrade = z.infer<typeof ActionGrade>;

export const AnalysisStatus = z.enum(["CREATED", "RUNNING", "COMPLETED", "FAILED"]);
export type AnalysisStatus = z.infer<typeof AnalysisStatus>;

export const ResultStatus = z.enum([
  "PENDING", "GENERATED", "VALIDATING", "VALIDATED", "HOLD", "REJECTED",
]);

export const CompanySize = z.enum(["SOLO", "MICRO", "SMALL", "MEDIUM", "LARGE"]);
export type CompanySize = z.infer<typeof CompanySize>;

export const ChangeType = z.enum(["NEW", "AMENDED", "DELETED", "UNCHANGED"]);

// ── 프로필 ───────────────────────────────────────────────────────────

/**
 * 사업 활동 질문에 대한 답.
 *
 * **`NO`와 `UNKNOWN`을 반드시 구분한다.** 체크박스 하나로 받으면 체크하지 않은
 * 것이 '아니오'인지 '아직 답하지 않음'인지 알 수 없고, 그러면 질문을 건너뛴
 * 사용자에게 '무관'이라고 단정하게 된다.
 */
export const ActivityAnswer = z.enum(["YES", "NO", "UNKNOWN"]);
export type ActivityAnswer = z.infer<typeof ActivityAnswer>;

export const ActivityAnswers = z.record(z.string(), ActivityAnswer);
export type ActivityAnswers = z.infer<typeof ActivityAnswers>;

/**
 * 온보딩이 그릴 질문. **문구는 백엔드가 준다.**
 *
 * 같은 목록을 프론트가 따로 들고 있으면 반드시 어긋난다. 항목이 하나 빠져도
 * 아무도 모르고, 사용자는 답할 기회조차 없는 질문 때문에 보류를 받는다.
 */
export const ActivityQuestion = z.object({
  activity: z.string(),
  question: z.string(),
  hint: z.string(),
  label: z.string(),
});
export type ActivityQuestion = z.infer<typeof ActivityQuestion>;

export const ActivityQuestionList = z.object({
  items: z.array(ActivityQuestion),
});

export const Profile = z.object({
  user_id: z.string(),
  job: z.string(),
  industry: z.string(),
  company_size: CompanySize,
  employee_count: z.number().nullable(),
  interests: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
  activities: ActivityAnswers,
});
export type Profile = z.infer<typeof Profile>;

export const ProfileInput = z.object({
  job: z.string().min(1, "직무를 입력해 주세요.").max(100),
  industry: z.string().min(1, "업종을 입력해 주세요.").max(100),
  company_size: CompanySize,
  employee_count: z.number().int().min(0).max(1_000_000).nullable(),
  interests: z.array(z.string()).max(20),
  activities: ActivityAnswers,
});
export type ProfileInput = z.infer<typeof ProfileInput>;

// ── 분석 ─────────────────────────────────────────────────────────────

export const Counts = z.object({
  action: z.number(),
  decision: z.number(),
  awareness: z.number(),
  hold: z.number(),
  not_applicable: z.number(),
  rejected: z.number(),
  total: z.number(),
});
export type Counts = z.infer<typeof Counts>;

export const Analysis = z.object({
  analysis_id: z.string(),
  status: AnalysisStatus,
  period_from: z.string().nullable(),
  period_to: z.string().nullable(),
  law_query: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  laws_examined: z.number(),
  articles_changed: z.number(),
  counts: Counts,
  error: z.string().nullable(),
  trace_id: z.string(),
});
export type Analysis = z.infer<typeof Analysis>;

export const AnalysisList = z.object({
  items: z.array(Analysis),
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
});

// ── 근거 (AP-05: 세 종류를 별도 타입으로) ────────────────────────────

/** 법제처 공식 원문. 모델이 생성하지 않는 값들이다. */
export const LegalEvidence = z.object({
  law_id: z.string(),
  law_name: z.string(),
  article_no: z.string(),
  article_title: z.string().nullable(),
  effective_date: z.string().nullable(),
  ministry: z.string().nullable(),
  source_url: z.string().nullable(),
  /** 원문 존재가 검증된 인용만 담긴다 (FR-021). */
  quoted_spans: z.array(z.string()),
});
export type LegalEvidence = z.infer<typeof LegalEvidence>;

/**
 * 위임된 하위법령 근거 (ADR-025). 법적 근거지만 **모법 조문이 아니다**.
 *
 * 모법 인용과 같은 목록에 담으면 시행령 구절이 모법 조문에서 나온 것처럼 보인다.
 * 사용자가 원문을 대조할 때 찾을 수 없는 문장을 보게 되므로 분리해서 표시한다.
 */
export const DelegatedEvidence = z.object({
  law_id: z.string(),
  law_name: z.string(),
  law_type: z.string().nullable(),
  article_no: z.string(),
  article_title: z.string().nullable(),
  source_url: z.string().nullable(),
  quoted_spans: z.array(z.string()),
  /** false면 이 조문이 기준을 별표 등으로 다시 넘긴다. */
  resolves_criterion: z.boolean(),
});
export type DelegatedEvidence = z.infer<typeof DelegatedEvidence>;

/** RAG 참고자료. 법적 권위를 갖지 않는다 (BR-004). */
export const ReferenceEvidence = z.object({
  doc_id: z.string(),
  title: z.string().nullable(),
  source: z.string(),
  agency: z.string().nullable(),
  published_at: z.string().nullable(),
  doc_type: z.string(),
  snippet: z.string(),
});
export type ReferenceEvidence = z.infer<typeof ReferenceEvidence>;

export const ChecklistItem = z.object({
  title: z.string(),
  detail: z.string().nullable(),
});

/**
 * AI 해석. 공식 사실 필드가 **없다** (FR-020).
 * 법령명·조문번호·시행일이 필요하면 LegalEvidence에서 가져와야 한다.
 */
export const AiInterpretation = z.object({
  reason: z.string(),
  matched_conditions: z.array(z.string()),
  /** 보류 해소에 필요한 정보. 사용자가 값을 넣으면 풀리는 것들만 담긴다. */
  missing_context: z.array(z.string()),
  impact_summary: z.string().nullable(),
  affected_work: z.array(z.string()),
  checklist: z.array(ChecklistItem),
  confidence: z.number().nullable(),
  model: z.string().nullable(),
});
export type AiInterpretation = z.infer<typeof AiInterpretation>;

export const Change = z.object({
  change_type: ChangeType,
  additions: z.array(z.string()),
  deletions: z.array(z.string()),
  delegation_targets: z.array(z.string()),
});
export type Change = z.infer<typeof Change>;

export const Validation = z.object({
  passed: z.boolean(),
  checks: z.record(z.string(), z.boolean()),
  failures: z.array(z.string()),
  dropped_span_count: z.number(),
});

export const Result = z.object({
  result_id: z.string(),
  analysis_id: z.string().nullable(),
  status: ResultStatus,
  applicability: Applicability,
  action_grade: ActionGrade.nullable(),
  change: Change,
  legal_evidence: LegalEvidence,
  delegated_evidence: z.array(DelegatedEvidence).default([]),
  reference_evidence: z.array(ReferenceEvidence),
  ai_interpretation: AiInterpretation,
  validation: Validation,
  created_at: z.string(),
});
export type Result = z.infer<typeof Result>;

export const ResultList = z.object({
  analysis_id: z.string(),
  status: AnalysisStatus,
  counts: Counts,
  items: z.array(Result),
});

export const Evidence = z.object({
  result_id: z.string(),
  legal_evidence: LegalEvidence,
  delegated_evidence: z.array(DelegatedEvidence).default([]),
  reference_evidence: z.array(ReferenceEvidence),
  ai_interpretation: AiInterpretation,
  disclaimer: z.string(),
});
export type Evidence = z.infer<typeof Evidence>;

// ── 저장 / 피드백 ────────────────────────────────────────────────────

// ── 보류 재판정 (FR-008) ─────────────────────────────────────────────

export const ReassessResult = z.object({
  revision_id: z.string(),
  original_result_id: z.string(),
  previous_applicability: Applicability,
  new_applicability: Applicability,
  /** 판정이 실제로 바뀌었는지 */
  changed: z.boolean(),
  message: z.string(),
  /** 사용자가 채운 정보. 이력에 보존된다 */
  added_context: z.record(z.string(), z.string()),
  result: Result,
});
export type ReassessResult = z.infer<typeof ReassessResult>;

export const Revision = z.object({
  revision_id: z.string(),
  original_result_id: z.string(),
  new_result_id: z.string(),
  previous_applicability: Applicability,
  new_applicability: Applicability,
  added_context: z.record(z.string(), z.string()),
  created_at: z.string(),
});
export type Revision = z.infer<typeof Revision>;

export const SavedRegulation = z.object({
  saved_id: z.string(),
  result_id: z.string(),
  law_id: z.string(),
  law_name: z.string(),
  article_no: z.string(),
  note: z.string().nullable(),
  created_at: z.string(),
});
export type SavedRegulation = z.infer<typeof SavedRegulation>;

export const Health = z.object({
  status: z.string(),
  env: z.string(),
  auth_mode: z.string(),
  law_api_configured: z.boolean(),
  llm_configured: z.boolean(),
  llm_model: z.string(),
});

// ── 에러 봉투 (명세서 §3) ────────────────────────────────────────────

export const ApiErrorBody = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    detail: z.string().nullable(),
  }),
});
