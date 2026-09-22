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

/**
 * 보류 상태인 결과 상세로 이동한다. 없으면 null을 돌려준다.
 *
 * 문구가 아니라 data 속성으로 찾는다. 카피가 바뀌어도 테스트가 살아 있어야 한다.
 */
export async function openHoldResult(page: Page): Promise<boolean> {
  const holdCard = page
    .locator('[data-testid="result-card"][data-applicability="HOLD"]')
    .first();

  if (!(await holdCard.isVisible().catch(() => false))) return false;

  await holdCard.getByRole("link", { name: /근거 보기/ }).click();
  await page.waitForURL(/\/results\//, { timeout: 20_000 });
  return true;
}

/**
 * 보류가 잘 나오는 프로필로 되돌린다.
 *
 * 재판정 테스트는 보류 결과가 있어야 의미가 있는데, 그것을 법제처가 이번에
 * 무엇을 개정했는지에 맡기면 테스트가 조용히 건너뛰어진다. **건너뛰는 테스트는
 * 실패하는 테스트보다 나쁘다** — 초록불인데 아무것도 검증하지 않는다.
 *
 * 두 가지를 되돌린다.
 *
 * - **상시근로자 수를 비운다.** 규모 조건이 있는 조문은 코드가 보류로 강등한다(AP-03).
 * - **사업 활동을 전부 '모름'으로 되돌린다.** 답이 채워져 있으면 대상 집단이
 *   확정되어 보류가 나오지 않는다. 앞선 스펙이 같은 데모 계정의 프로필을
 *   채워 두는 탓에 실제로 이것 때문에 실패했다 — 스펙 사이의 상태 누수다.
 */
export async function makeHoldProne(page: Page): Promise<void> {
  await page.goto("/settings");

  const field = page.getByLabel(/상시근로자 수/);
  await field.waitFor({ state: "visible", timeout: 20_000 });
  await field.fill("");

  const unknowns = page.locator('[data-testid$="-UNKNOWN"]');
  const count = await unknowns.count();
  for (let i = 0; i < count; i += 1) {
    await unknowns.nth(i).click();
  }

  await page.getByRole("button", { name: /변경 사항 저장/ }).click();
  await expect(page.getByText("저장되었습니다.")).toBeVisible({ timeout: 20_000 });
}

export async function findHoldResult(
  page: Page,
  laws: string[] = ["근로기준법", "산업안전보건법", "개인정보 보호법"],
): Promise<void> {
  const tried: string[] = [];
  for (const law of laws) {
    await page.goto("/dashboard");
    await runAnalysis(page, law);
    tried.push(law);
    if (await openHoldResult(page)) return;
  }
  throw new Error(
    `보류 결과를 찾지 못했습니다 (시도: ${tried.join(", ")}). ` +
      "상시근로자 수를 비웠는데도 어느 법령에서도 보류가 나오지 않으면 " +
      "규모 기준 판정(AP-03)이나 보류 강등 정책이 깨진 것입니다.",
  );
}
