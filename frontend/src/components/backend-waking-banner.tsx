"use client";

import { useEffect, useState } from "react";

import { type BackendState, onBackendState } from "@/lib/api";

/**
 * 백엔드가 깨어나는 동안 그 사실을 알린다.
 *
 * 무료 호스팅은 일정 시간 요청이 없으면 인스턴스를 잠재우고, 다시 깨우는 데
 * 30~60초가 걸린다. 그동안 화면은 그냥 멈춰 있고 사용자는 고장으로 읽는다.
 *
 * 무료 티어를 쓰는 것 자체는 선택이지만, 그 대가를 사용자에게 숨기는 것은
 * 다른 문제다. 기다려야 한다는 사실과 이유를 말해 주는 편이 정직하다.
 */
export function BackendWakingBanner() {
  const [state, setState] = useState<BackendState>("awake");

  useEffect(() => onBackendState(setState), []);

  if (state !== "waking") return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="backend-waking"
      className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <span className="inline-block animate-pulse">●</span>{" "}
      서버를 깨우는 중입니다. 무료 호스팅이라 한동안 요청이 없으면 잠들며, 처음 한
      번은 30초에서 1분쯤 걸립니다.
    </div>
  );
}
