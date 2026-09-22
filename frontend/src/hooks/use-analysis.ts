"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/lib/api";

export const analysisKeys = {
  list: ["analyses"] as const,
  detail: (id: string) => ["analyses", id] as const,
  results: (id: string, includeNotApplicable: boolean) =>
    ["analyses", id, "results", includeNotApplicable] as const,
};

/**
 * 분석 실행.
 *
 * 백엔드는 202로 analysis_id만 먼저 준다. 실제 분석은 수십 초 걸리므로
 * 이 훅이 완료될 때까지 상태를 폴링한다 (NFR-006).
 */
export function useRunAnalysis() {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);

  /**
   * 화면에 들어올 때 가장 최근 분석을 이어받는다.
   *
   * activeId는 React 상태라서 새로고침하거나 다른 화면에 갔다 오면 사라진다.
   * 그러면 분석이 돌고 있거나 이미 끝났는데도 대시보드가 "아직 분석한 규제
   * 변화가 없습니다"로 돌아간다. 무료 호스팅에서 분석이 몇 분 걸리는 탓에
   * 기다리다 새로고침하면 바로 이 상태가 됐다.
   *
   * 분석 결과는 서버에 남아 있다. 화면이 그것을 못 찾고 있었을 뿐이다.
   */
  const latest = useQuery({
    queryKey: [...analysisKeys.list, "latest"],
    queryFn: () => api.listAnalyses(1, 0),
    staleTime: 0,
  });

  const latestId = latest.data?.items[0]?.analysis_id ?? null;
  const effectiveId = activeId ?? latestId;

  const start = useMutation({
    mutationFn: (input: { law_query?: string; max_laws?: number }) =>
      api.createAnalysis(input),
    onSuccess: (analysis) => {
      setActiveId(analysis.analysis_id);
      queryClient.invalidateQueries({ queryKey: analysisKeys.list });
    },
    onError: (error) => {
      // 이미 진행 중인 분석이 있으면 그것을 이어서 따라간다.
      if (error instanceof ApiError && error.isAnalysisInProgress) {
        const existing = error.detail?.match(/analysis_id=(\S+)/)?.[1];
        if (existing) setActiveId(existing);
      }
    },
  });

  const tracked = useQuery({
    queryKey: analysisKeys.detail(effectiveId ?? ""),
    queryFn: () => api.getAnalysis(effectiveId!),
    enabled: Boolean(effectiveId),
    // 끝나면 폴링을 멈춘다.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "COMPLETED" || status === "FAILED" ? false : 2000;
    },
  });

  const analysis = tracked.data ?? null;
  const isRunning =
    start.isPending ||
    (analysis !== null && (analysis.status === "RUNNING" || analysis.status === "CREATED"));

  return {
    start,
    analysis,
    activeId: effectiveId,
    isRunning,
    reset: () => setActiveId(null),
    startError: start.error instanceof ApiError ? start.error : null,
  };
}

export function useResults(analysisId: string | null, includeNotApplicable: boolean) {
  return useQuery({
    queryKey: analysisKeys.results(analysisId ?? "", includeNotApplicable),
    queryFn: () => api.getResults(analysisId!, { includeNotApplicable }),
    enabled: Boolean(analysisId),
  });
}

export function useAnalysisHistory() {
  return useQuery({
    queryKey: analysisKeys.list,
    queryFn: () => api.listAnalyses(20, 0),
  });
}
