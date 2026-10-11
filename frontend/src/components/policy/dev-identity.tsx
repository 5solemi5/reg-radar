"use client";

import { useState } from "react";

import { Button, Card, SectionTitle } from "@/components/ui";
import { devUserId, setDevUserId } from "@/lib/api";
import { isAuthConfigured } from "@/lib/supabase";

/**
 * 로컬 dev 모드 전용 — 사용자 전환.
 *
 * 4-eyes 규칙 때문에 승인을 시연하려면 제출자와 다른 준법감시인이 필요하다.
 * 백엔드 POLICY_MEMBERS(.env.example)의 기본값과 같은 ID를 쓴다. Supabase 인증이
 * 설정된 배포에서는 그리지 않는다(실제 계정으로 로그인해야 한다).
 */
const DEMO_USERS = [
  { id: "dev-user", label: "현업 담당 (STAFF)" },
  { id: "dev-officer", label: "준법감시인 (COMPLIANCE_OFFICER)" },
];

export function DevIdentitySwitch() {
  const [current, setCurrent] = useState(() => devUserId());
  if (isAuthConfigured) return null;

  return (
    <section className="mt-10">
      <SectionTitle hint="로컬 개발 모드에서만 보입니다. 백엔드 POLICY_MEMBERS에 등록된 ID여야 합니다.">
        사용자 전환 (개발용)
      </SectionTitle>
      <Card className="flex flex-wrap items-center gap-3">
        <span className="text-sm">지금: <strong data-testid="dev-user-id">{current}</strong></span>
        {DEMO_USERS.map((u) => (
          <Button
            key={u.id}
            variant={u.id === current ? "primary" : "secondary"}
            onClick={() => {
              setDevUserId(u.id);
              setCurrent(u.id);
              window.location.reload(); // 캐시된 응답을 다른 사용자 것으로 보지 않게
            }}
          >
            {u.label}
          </Button>
        ))}
      </Card>
    </section>
  );
}
