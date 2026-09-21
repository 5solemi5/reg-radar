/**
 * 백엔드 API 클라이언트.
 *
 * 모든 응답을 Zod로 검증한다. 계약이 어긋나면 화면이 undefined로 조용히 깨지는
 * 대신 어디서 어긋났는지 즉시 드러난다.
 */
import { z } from "zod";

import {
  Analysis,
  AnalysisList,
  ApiErrorBody,
  Evidence,
  Health,
  Profile,
  type ProfileInput,
  Result,
  ResultList,
  SavedRegulation,
} from "./schemas";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

/**
 * 현재 인증은 백엔드의 dev 모드(X-User-Id 헤더)에 맞춘다.
 * W4에서 Supabase JWT로 교체되며, 그때 이 함수만 바꾸면 된다.
 */
const USER_ID_KEY = "reg-radar-user-id";

export function getUserId(): string {
  if (typeof window === "undefined") return "anonymous";
  let id = window.localStorage.getItem(USER_ID_KEY);
  if (!id) {
    id = `user-${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(USER_ID_KEY, id);
  }
  return id;
}

export function resetUserId(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(USER_ID_KEY);
}

/** 백엔드 에러 봉투(명세서 §3)를 그대로 옮긴 예외. */
export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly detail?: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** 프로필 미설정 — 온보딩으로 보내야 하는 신호 (FR-002). */
  get isProfileMissing(): boolean {
    return this.status === 404 || this.code === "profile_required";
  }

  get isAnalysisInProgress(): boolean {
    return this.code === "analysis_in_progress";
  }
}

async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-User-Id": getUserId(),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    // 서버가 꺼져 있거나 네트워크가 끊긴 경우. 사용자가 다음에 뭘 해야 할지 말해준다.
    throw new ApiError(
      "network_error",
      "서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인해 주세요.",
      0,
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const parsed = ApiErrorBody.safeParse(body);
    if (parsed.success) {
      const { code, message, detail } = parsed.data.error;
      throw new ApiError(code, message, response.status, detail);
    }
    // FastAPI 기본 422(스키마 위반) 등 봉투 형식이 아닌 응답
    throw new ApiError(
      "unexpected_error",
      `요청이 실패했습니다 (${response.status}).`,
      response.status,
      typeof text === "string" ? text.slice(0, 300) : undefined,
    );
  }

  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    // 백엔드 계약 위반. 조용히 넘기면 화면이 나중에 이상하게 깨진다.
    console.error("API 응답이 스키마와 다릅니다", path, parsed.error.issues);
    throw new ApiError(
      "contract_mismatch",
      "서버 응답 형식이 예상과 다릅니다. 백엔드 버전을 확인해 주세요.",
      response.status,
      parsed.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join(", "),
    );
  }
  return parsed.data;
}

const json = (body: unknown): RequestInit => ({ body: JSON.stringify(body) });

export const api = {
  health: () => request("/health", Health),

  getProfile: () => request("/profile", Profile),
  putProfile: (input: ProfileInput) =>
    request("/profile", Profile, { method: "PUT", ...json(input) }),
  patchProfile: (input: Partial<ProfileInput>) =>
    request("/profile", Profile, { method: "PATCH", ...json(input) }),

  createAnalysis: (input: { law_query?: string; max_laws?: number }) =>
    request("/analyses", Analysis, { method: "POST", ...json(input) }),
  getAnalysis: (id: string) => request(`/analyses/${id}`, Analysis),
  listAnalyses: (limit = 20, offset = 0) =>
    request(`/analyses?limit=${limit}&offset=${offset}`, AnalysisList),
  cancelAnalysis: (id: string) =>
    request(`/analyses/${id}`, z.undefined(), { method: "DELETE" }),
  getResults: (id: string, opts?: { includeNotApplicable?: boolean }) =>
    request(
      `/analyses/${id}/results?include_not_applicable=${opts?.includeNotApplicable ?? false}`,
      ResultList,
    ),

  getResult: (id: string) => request(`/results/${id}`, Result),
  getEvidence: (id: string) => request(`/results/${id}/evidence`, Evidence),
  submitFeedback: (id: string, input: { helpful: boolean; comment?: string }) =>
    request(`/results/${id}/feedback`, z.looseObject({}), {
      method: "POST",
      ...json(input),
    }),

  listSaved: () => request("/saved-regulations", z.array(SavedRegulation)),
  saveRegulation: (input: { result_id: string; note?: string }) =>
    request("/saved-regulations", SavedRegulation, { method: "POST", ...json(input) }),
  deleteSaved: (id: string) =>
    request(`/saved-regulations/${id}`, z.undefined(), { method: "DELETE" }),
};
