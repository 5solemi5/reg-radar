import { expect, test } from "@playwright/test";

import { runAnalysis } from "./helpers";

/**
 * 가입 없이 둘러보기 (체험 모드).
 *
 * 심사나 데모에서 가입 절차가 서비스를 보기도 전에 포기하게 만드는 문턱이라
 * 익명 로그인을 뒀다. 공용 계정을 쓰지 않는 이유는 공개 저장소·공개 사이트에
 * 비밀번호를 적어야 하고, 들어온 사람들이 서로의 데이터를 보게 되기 때문이다.
 */
test.describe.configure({ mode: "serial" });

test.describe("체험 모드", () => {
  test("가입 없이 들어가 프로필까지 채운다", async ({ page }) => {
    await page.goto("/login");

    await page.getByTestId("guest-login").click();
    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });

    // 데이터가 이 브라우저에만 남는다는 사실을 계속 알려야 한다. 말해주지
    // 않으면 나중에 사라졌을 때 고장으로 읽힌다.
    await expect(page.getByTestId("guest-badge")).toBeVisible();

    // 예시 프로필로 입력을 건너뛴다 — 체험의 핵심은 여기까지 두 번 클릭이다.
    await page.getByTestId("preset-p02_it_hr").click({ timeout: 20_000 });
    await expect(page.getByLabel(/업종/)).toHaveValue("IT 서비스");
    await expect(page.getByLabel(/상시근로자 수/)).toHaveValue("80");

    await page.getByRole("button", { name: /저장하고 시작하기|변경 사항 저장/ }).click();
    await page.waitForURL(/\/dashboard/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "규제 대시보드" })).toBeVisible();
  });

  test("체험 세션은 서로 분리된다", async ({ browser }) => {
    /**
     * 공용 계정이었다면 모두가 같은 데이터를 봤을 것이다. 익명 로그인은
     * 사람마다 별도 사용자를 만들어 준다.
     */
    const first = await browser.newPage();
    await first.goto("/login");
    await first.getByTestId("guest-login").click();
    await first.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });

    const second = await browser.newPage();
    await second.goto("/login");
    await second.getByTestId("guest-login").click();
    await second.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });

    // 첫 번째만 프로필을 채운다.
    await first.getByTestId("preset-p01_commerce").click({ timeout: 20_000 });
    await first.getByRole("button", { name: /저장하고 시작하기|변경 사항 저장/ }).click();
    await first.waitForURL(/\/dashboard/, { timeout: 30_000 });

    // 두 번째는 여전히 프로필이 없어야 한다 — 데이터가 섞이지 않는다.
    await second.goto("/dashboard");
    await expect(second).toHaveURL(/\/onboarding/, { timeout: 30_000 });

    await first.close();
    await second.close();
  });

  test("새로고침해도 진행 중인 분석을 이어받는다", async ({ browser }) => {
    /**
     * activeId가 React 상태라서 새로고침하면 사라지고, 분석이 돌고 있거나
     * 이미 끝났는데도 대시보드가 "아직 분석한 규제 변화가 없습니다"로
     * 돌아갔다. 무료 호스팅에서 분석이 몇 분 걸리는 탓에 기다리다
     * 새로고침하면 바로 이 상태가 됐다.
     *
     * 결과는 서버에 남아 있다. 화면이 그것을 못 찾고 있었을 뿐이다.
     */
    const page = await browser.newPage();
    await page.goto("/login");
    await page.getByTestId("guest-login").click();
    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });

    await page.getByTestId("preset-p02_it_hr").click({ timeout: 20_000 });
    await page.getByRole("button", { name: /저장하고 시작하기|변경 사항 저장/ }).click();
    await page.waitForURL(/\/dashboard/, { timeout: 30_000 });

    await runAnalysis(page, "근로기준법");
    const before = await page.locator('[data-testid="result-card"]').count();
    expect(before).toBeGreaterThan(0);

    // 새로고침 — 여기서 빈 화면으로 돌아가면 안 된다.
    await page.reload();
    await expect(page.locator('[data-testid="result-card"]').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("아직 분석한 규제 변화가 없습니다")).toHaveCount(0);

    await page.close();
  });
});
