import { expect, test, type Page } from "@playwright/test";

import { ensureProfile, openFirstResult, runAnalysis, signIn } from "./helpers";

/**
 * 화면이 지켜야 하는 신뢰성 약속.
 *
 * 이 프로젝트의 차별점은 "AI가 지어내지 않는다"이므로, 그것이 화면에서
 * 실제로 보이는지 확인한다.
 */
test.describe.configure({ mode: "serial" });

test.describe("신뢰성 표시", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await signIn(page);
    await ensureProfile(page);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("법률 자문이 아님을 모든 화면에서 고지한다", async () => {
    for (const path of ["/dashboard", "/history", "/saved", "/settings"]) {
      await page.goto(path);
      await expect(page.getByText(/법률 자문이 아니라/).first()).toBeVisible();
    }
  });

  test("근거 블록이 각각의 성격을 명시한다", async () => {
    await page.goto("/dashboard");
    await runAnalysis(page, "근로기준법");
    await openFirstResult(page);

    // 법적 근거는 법제처 원문임을 밝힌다 (AP-05)
    await expect(page.getByText(/법제처 공식 원문/)).toBeVisible();
    // 참고자료는 법적 근거와 다름을 밝힌다 (BR-004)
    await expect(page.getByText(/법적 근거와 동일한 권위를 갖지 않습니다/)).toBeVisible();
    // AI 해석은 법적 결론이 아님을 밝힌다
    await expect(page.getByText(/법적 결론이 아닙니다/)).toBeVisible();
    // 변경 구간은 AI 생성물이 아님을 밝힌다 (BR-002)
    await expect(page.getByText(/AI가 만든 것이 아닙니다/)).toBeVisible();
  });
});
