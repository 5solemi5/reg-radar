import { expect, type Page } from "@playwright/test";

/**
 * 테스트 계정.
 *
 * 비밀번호는 기본값을 두지 않는다. 저장소에 비밀번호를 적어두면 그 값이
 * 실제로 쓰이는 계정의 비밀번호가 되고, 되돌리기 어렵다.
 * `.env.e2e.local`(gitignore됨)이나 셸 환경변수로 넘긴다.
 */
export const DEMO_EMAIL = process.env.E2E_EMAIL ?? "demo.hr@regradar.app";
export const DEMO_PASSWORD = process.env.E2E_PASSWORD ?? "";

export const PROFILE = {
  job: "HR 담당자 (채용·근태·취업규칙)",
  industry: "IT 서비스",
  employeeCount: "80",
  interests: ["노동·인사", "개인정보"],
};

/**
 * 로그인한다.
 *
 * `/dashboard`로 가서 리다이렉트를 관찰하는 방식은 쓰지 않는다. goto 직후
 * URL은 아직 /dashboard라서 "이미 로그인됨"으로 잘못 판단하게 된다 —
 * 실제로 이 버그로 여정 테스트 6개가 전부 실패했다. 로그인 화면으로 직접
 * 가서 상태를 확정한다.
 */
export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");

  const emailBox = page.getByLabel("이메일");
  const devNotice = page.getByText("인증이 설정되지 않았습니다");

  // 로그인 화면은 세션을 확인하는 동안 스피너를 먼저 보여준다. isVisible()은
  // 즉시 판정이라 그 시점에 "폼이 없다"로 잘못 읽힌다 — 실제로 이 때문에
  // 입력을 건너뛰고 타임아웃이 났다. 셋 중 하나가 확정될 때까지 기다린다.
  await expect(emailBox.or(devNotice)).toBeVisible({ timeout: 30_000 });

  // 인증 미설정(dev 모드) 환경에서는 안내만 보여준다.
  if (await devNotice.isVisible()) {
    await page.goto("/dashboard");
    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });
    return;
  }

  if (!DEMO_PASSWORD) {
    throw new Error(
      "E2E_PASSWORD가 설정되지 않았습니다. " +
        "frontend/.env.e2e.local에 E2E_EMAIL/E2E_PASSWORD를 넣거나 환경변수로 넘기세요.",
    );
  }

  await emailBox.fill(DEMO_EMAIL);
  await page.getByLabel("비밀번호").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "로그인", exact: true }).last().click();

  await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });
}

/** 프로필이 없으면 온보딩을 채운다. */
export async function ensureProfile(page: Page): Promise<void> {
  if (!page.url().includes("/onboarding")) return;

  await page.getByLabel(/직무/).fill(PROFILE.job);
  await page.getByLabel(/업종/).fill(PROFILE.industry);
  await page.getByLabel(/회사 규모/).selectOption("MEDIUM");
  await page.getByLabel(/상시근로자 수/).fill(PROFILE.employeeCount);
  for (const interest of PROFILE.interests) {
    await page.getByRole("button", { name: interest, exact: true }).click();
  }
  await page.getByRole("button", { name: /저장하고 시작하기/ }).click();
  await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
}

/**
 * 분석을 실행하고 완료될 때까지 기다린다.
 *
 * 실제 법제처 조회와 조문별 LLM 호출이 이어지므로 수십 초 걸린다.
 */
export async function runAnalysis(page: Page, lawQuery?: string): Promise<void> {
  if (lawQuery) {
    await page.getByLabel("분석할 법령 이름").fill(lawQuery);
  }
  await page
    .getByRole("button", { name: /규제 변화 분석|지금 분석하기/ })
    .first()
    .click();

  // 진행 상태를 반드시 보여야 한다 (NFR-006, NFR-013).
  await expect(page.getByText("분석 중")).toBeVisible({ timeout: 15_000 });

  // 완료되면 요약이 나타난다.
  await expect(page.getByRole("heading", { name: "요약" })).toBeVisible({
    timeout: 150_000,
  });
}

/** 결과 상세로 이동한다. 해당/보류가 없으면 무관 항목을 펼친다 (FR-015). */
export async function openFirstResult(page: Page): Promise<void> {
  const link = page.getByRole("link", { name: /근거 보기/ }).first();
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByLabel("무관 항목도 보기").check();
  }
  await page.getByRole("link", { name: /근거 보기/ }).first().click();
  await page.waitForURL(/\/results\//, { timeout: 20_000 });
}
