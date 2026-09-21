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
    queryKey: analysisKeys.detail(activeId ?? ""),
    queryFn: () => api.getAnalysis(activeId!),
    enabled: Boolean(activeId),
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
    activeId,
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
