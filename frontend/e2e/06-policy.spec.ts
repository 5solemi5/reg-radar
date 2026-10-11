import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * 사내 규정 개정 초안 승인 화면 (문서 12 §6-8).
 *
 * 다른 E2E와 달리 **백엔드·LLM 없이** 돈다. /policy API를 브라우저에서 가로채 작은
 * 상태 기계로 응답한다 — 초안 생성에는 LLM 호출(과금)이 필요해서, 화면 흐름만 따로
 * 검증한다. 권한 규칙 자체는 백엔드 테스트(test_policy_workflow_repo.py)가 지킨다.
 * 여기서는 "서버가 막으면 그 사유를 그대로 보여주는가"와 상태별 화면을 본다.
 *
 * 인증이 설정된 빌드(Supabase)에서는 로그인으로 보내지므로 건너뛴다.
 */

const DRAFT_ID = "11111111-2222-3333-4444-555555555555";
const CURRENT = "가산휴가를 포함한 총 휴가 일수는 20일을 한도로 한다.";
const PROPOSED = "가산휴가를 포함한 총 휴가 일수는 25일을 한도로 한다.";

type Draft = {
  draft_id: string; law_ref: string; policy_ref: string; relation: string; state: string;
  current_text: string; proposed_text: string; issues: string[]; created_by: string;
  submitted_by: string | null; decided_by: string | null;
  comments: { user_id: string; text: string }[];
};

function fakeServer(page: Page) {
  const draft: Draft = {
    draft_id: DRAFT_ID, law_ref: "근로기준법 제60조", policy_ref: "HR-01 제22조",
    relation: "CONFLICT", state: "DRAFTED", current_text: CURRENT, proposed_text: PROPOSED,
    issues: ["원문에 근거가 없는 수치: ['30일']"], created_by: "dev-user",
    submitted_by: null, decided_by: null, comments: [],
  };
  const events: { action: string; actor: string; before: string | null; after: string }[] = [
    { action: "create", actor: "dev-user", before: null, after: "DRAFTED" },
  ];
  const roles: Record<string, string> = { "dev-user": "STAFF", "dev-officer": "COMPLIANCE_OFFICER" };

  const json = (route: Route, status: number, body: unknown) =>
    route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
  const error = (route: Route, status: number, code: string, message: string) =>
    json(route, status, { error: { code, message, detail: null } });

  return page.route("**/api/v1/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname.replace(/^.*\/api\/v1/, "");
    const user = req.headers()["x-user-id"] ?? "";
    if (!path.startsWith("/policy")) return error(route, 404, "not_found", "없음");
    if (!roles[user]) return error(route, 403, "policy_forbidden", "이 조직의 구성원이 아니다");

    const move = (action: string, to: string) => {
      events.push({ action, actor: user, before: draft.state, after: to });
      draft.state = to;
    };

    if (path === "/policy/drafts") return json(route, 200, [draft]);
    if (path === `/policy/drafts/${DRAFT_ID}`) return json(route, 200, draft);
    if (path === "/policy/audit") {
      return json(route, 200, {
        intact: true, broken_at: null,
        events: events.map((e, seq) => ({
          org_id: "virtual-card-co", seq, at: "2026-10-11T09:00:00+00:00", actor: e.actor,
          role: roles[e.actor], action: e.action, draft_id: DRAFT_ID, before: e.before,
          after: e.after, detail: {}, prev_hash: "0".repeat(64), hash: `${seq}`.padEnd(64, "a"),
        })),
      });
    }
    if (path.endsWith("/submit")) {
      draft.submitted_by = user;
      move("submit", "IN_REVIEW");
      return json(route, 200, draft);
    }
    if (path.endsWith("/approve")) {
      if (roles[user] !== "COMPLIANCE_OFFICER") {
        return error(route, 403, "policy_forbidden", "승인·반려는 준법감시인만 할 수 있다");
      }
      if (user === draft.submitted_by) {
        return error(route, 403, "policy_forbidden", "제출자는 자기 초안을 승인·반려할 수 없다(4-eyes)");
      }
      if (draft.issues.length && !req.postDataJSON()?.acknowledged_issues) {
        return error(route, 409, "policy_conflict", "검증 문제 1건을 확인했다고 표시해야 승인된다");
      }
      draft.decided_by = user;
      move("approve", "APPROVED");
      return json(route, 200, draft);
    }
    return error(route, 404, "not_found", "없음");
  });
}

async function asUser(page: Page, id: string) {
  await page.evaluate((v) => window.localStorage.setItem("reg-radar-user-id", v), id);
}

test("초안 비교 → 검토 요청 → 권한 거부 사유 표시 → 준법감시인 승인 → 감사 로그", async ({ page }) => {
  await fakeServer(page);
  await page.goto("/policy");
  if (page.url().includes("/login")) test.skip(true, "인증이 설정된 빌드 — dev 모드 빌드에서 돈다");
  await asUser(page, "dev-user");
  await page.goto(`/policy/${DRAFT_ID}`);

  // 현행 ↔ 개정안: 바뀐 어절만 삭제·추가로 표시한다
  const diff = page.getByTestId("draft-diff");
  await expect(diff.locator("del")).toHaveText("20일을");
  await expect(diff.locator("ins")).toHaveText("25일을");
  await expect(page.getByText("검증 문제 1건")).toBeVisible();

  await page.getByRole("button", { name: "검토 요청" }).click();
  await expect(page.getByTestId("draft-state")).toHaveText("검토 중");

  // 현업이 승인 → 서버 사유를 그대로
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await expect(page.getByTestId("action-error")).toHaveText("승인·반려는 준법감시인만 할 수 있다");

  // 준법감시인: 검증 문제 확인 없이 승인 → 409 사유, 확인 후 승인
  await asUser(page, "dev-officer");
  await page.reload();
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await expect(page.getByTestId("action-error")).toContainText("확인했다고 표시해야");
  await page.getByLabel("검증 문제를 확인했습니다").check();
  await page.getByRole("button", { name: "승인", exact: true }).click();
  await expect(page.getByTestId("draft-state")).toHaveText("승인");

  await page.goto("/policy");
  await expect(page.getByTestId("audit-integrity")).toHaveText("체인 검증 통과 · 3건");
});

test("조직 구성원이 아니면 안내만 보인다", async ({ page }) => {
  await fakeServer(page);
  await page.goto("/policy");
  if (page.url().includes("/login")) test.skip(true, "인증이 설정된 빌드");
  await asUser(page, "stranger");
  await page.reload();
  await expect(page.getByText("사내 규정 조직 구성원만 볼 수 있습니다")).toBeVisible();
});
