import { expect, test } from "@playwright/test";

import { DEMO_EMAIL, DEMO_PASSWORD } from "./helpers";

/** FR-001, NFR-007. 인증되지 않은 사용자는 보호 화면에 접근할 수 없다. */
test.describe("인증", () => {
  test("미인증 상태에서 대시보드에 접근하면 로그인으로 보낸다", async ({ page, request }) => {
    const base =
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
    const health = await (await request.get(`${base}/health`)).json();
    test.skip(health.auth_mode === "dev", "AUTH_MODE=dev — 인증이 비활성화된 환경");

    await page.goto("/dashboard");

    // goto 직후 URL은 아직 /dashboard다. 리다이렉트를 명시적으로 기다려야 한다.
    await page.waitForURL(/\/login/, { timeout: 30_000 });

    // 어디로 돌아가야 하는지 기억해야 한다.
    expect(page.url()).toContain("next=");
    await expect(page.getByRole("heading", { name: "규제 레이더" })).toBeVisible();
  });

  test("잘못된 비밀번호는 거부하고 이유를 알려준다", async ({ page }) => {
    await page.goto("/login");
    if (await page.getByText("인증이 설정되지 않았습니다").isVisible().catch(() => false)) {
      test.skip(true, "인증 미설정 환경");
    }

    await page.getByLabel("이메일").fill(DEMO_EMAIL);
    await page.getByLabel("비밀번호").fill("wrong-password-12345");
    await page.getByRole("button", { name: "로그인", exact: true }).last().click();

    await expect(page.getByRole("alert")).toBeVisible({ timeout: 20_000 });
    await expect(page).toHaveURL(/\/login/);
  });

  test("올바른 자격으로 로그인하면 들어간다", async ({ page }) => {
    await page.goto("/login");
    if (await page.getByText("인증이 설정되지 않았습니다").isVisible().catch(() => false)) {
      test.skip(true, "인증 미설정 환경");
    }

    test.skip(!DEMO_PASSWORD, "E2E_PASSWORD 미설정");

    await page.getByLabel("이메일").fill(DEMO_EMAIL);
    await page.getByLabel("비밀번호").fill(DEMO_PASSWORD);
    await page.getByRole("button", { name: "로그인", exact: true }).last().click();

    await page.waitForURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });
    await expect(page.getByText(DEMO_EMAIL)).toBeVisible();
  });
});
