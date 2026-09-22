import { expect, test, type Page } from "@playwright/test";

import { ensureProfile, findHoldResult, makeHoldProne, signIn } from "./helpers";

/**
 * 보류 재판정 (FR-008, BR-008).
 *
 * 보류는 "무엇을 알면 확정할 수 있는지"를 이미 말하고 있다. 사용자가 설정
 * 화면까지 가서 분석을 처음부터 다시 돌리게 만들지 않는다.
 */
test.describe.configure({ mode: "serial" });

test.describe("보류 재판정", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await signIn(page);
    await ensureProfile(page);

    // 보류를 법제처가 이번에 무엇을 개정했는지에 맡기지 않는다. 앞선 스펙이
    // 같은 데모 계정의 프로필을 채워 두므로 명시적으로 되돌린다.
    await makeHoldProne(page);
    await findHoldResult(page);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("보류 결과에 해소 폼이 함께 보인다", async () => {
    await expect(page.getByText("이 정보가 있으면 확정할 수 있습니다")).toBeVisible();
    await expect(
      page.getByRole("button", { name: /이 정보로 다시 판단하기/ }),
    ).toBeVisible();

    // 이 조문만 다시 본다는 것을 밝힌다.
    await expect(page.getByText(/분석 전체를 다시 돌리지 않습니다/)).toBeVisible();
  });

  test("정보를 채우면 다시 판단하고 이전 판정을 보존한다", async () => {
    await page
      .getByPlaceholder("판단에 필요한 다른 정보가 있다면 적어 주세요")
      .fill("E2E 테스트: 해당 설비나 활동을 운영하지 않습니다.");
    await page.getByRole("button", { name: /이 정보로 다시 판단하기/ }).click();

    // 재판정은 LLM 호출이라 수 초 걸린다.
    await expect(page.getByText(/바뀌었습니다|판정은 그대로입니다/)).toBeVisible({
      timeout: 120_000,
    });

    // BR-008: 이전 판정이 보존된다는 것을 화면이 밝힌다.
    await expect(page.getByText(/이전 판정은 그대로 보존됩니다/)).toBeVisible();
    await expect(page.getByText("반영한 정보")).toBeVisible();
  });
});
