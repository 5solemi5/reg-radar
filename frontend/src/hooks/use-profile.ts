"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api } from "@/lib/api";
import type { ProfileInput } from "@/lib/schemas";

export const profileKey = ["profile"] as const;

/**
 * 프로필 조회.
 *
 * 404는 오류가 아니라 **"아직 온보딩을 안 했다"는 신호**다 (FR-002 AC).
 * 그래서 에러로 던지지 않고 `needsOnboarding`으로 구분해 돌려준다.
 */
export function useProfile() {
  const query = useQuery({
    queryKey: profileKey,
    queryFn: async () => {
      try {
        return await api.getProfile();
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });

  return {
    ...query,
    profile: query.data ?? null,
    needsOnboarding: query.isSuccess && query.data === null,
  };
}

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: ProfileInput) => api.putProfile(input),
    onSuccess: (profile) => {
      queryClient.setQueryData(profileKey, profile);
    },
  });
}
