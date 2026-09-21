import { expect, test, type Page } from "@playwright/test";

import { ensureProfile, openFirstResult, runAnalysis, signIn } from "./helpers";

/**
 * 핵심 사용자 여정 (02 페르소나 문서 §4, UC-01~UC-11).
 *
 * **분석을 한 번만 실행하고 이어서 검증한다.** 테스트마다 분석을 돌리면
 * 매번 법제처 조회 + 조문별 LLM 호출이라 수 분이 걸리고, 사용자당 진행 중인
 * 분석이 하나뿐이라는 제약(FR-003)과도 부딪힌다. 실제 여정도 순차적이다.
 */
test.describe.configure({ mode: "serial" });

test.describe("사용자 여정", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await signIn(page);
    await ensureProfile(page);
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("① 대시보드가 내 프로필 기준임을 보여준다", async () => {
    await expect(page.getByRole("heading", { name: "규제 대시보드" })).toBeVisible();
    await expect(page.getByText("IT 서비스")).toBeVisible();
  });

  test("② 분석을 실행하면 진행 상태를 보여주고 결과를 낸다", async () => {
    await runAnalysis(page, "근로기준법");

    // FR-015. 판정별 건수를 식별할 수 있어야 한다.
    for (const label of ["조치 필요", "방침 결정", "인지", "보류", "무관"]) {
      await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
    }
  });

  test("③ 상세로 이동하면 세 근거가 분리되어 보인다", async () => {
    await openFirstResult(page);

    // AP-05 / FR-014
    await expect(page.getByText("법적 근거", { exact: true })).toBeVisible();
    await expect(page.getByText("참고 자료", { exact: true })).toBeVisible();
    await expect(page.getByText("AI 해석", { exact: true })).toBeVisible();

    // FR-012. 법제처 원문으로 갈 수 있어야 한다.
    await expect(page.getByRole("link", { name: /법제처에서 원문 보기/ })).toBeVisible();
  });

  test("④ 무엇이 바뀌었는지 변경 구간을 보여준다", async () => {
    // FR-005. 신구법 변경 구간은 법제처가 표시한 것이다.
    await expect(page.getByRole("heading", { name: "무엇이 바뀌었나" })).toBeVisible();
    await expect(page.getByText(/법제처 신구법 비교가 표시한 변경 구간/)).toBeVisible();
  });

  test("⑤ 규제를 저장하면 저장함에서 확인된다", async () => {
    const note = `E2E ${Date.now()}`;
    await page.getByPlaceholder("메모 (선택)").fill(note);
    await page.getByRole("button", { name: "저장함에 담기" }).click();
    await expect(page.getByRole("button", { name: "저장됨" })).toBeVisible();

    await page.getByRole("link", { name: "저장함" }).click();
    await expect(page.getByText(note)).toBeVisible({ timeout: 20_000 });
  });

  test("⑥ 분석 이력에 기록이 남는다", async () => {
    await page.getByRole("link", { name: "분석 이력" }).click();
    await expect(page.getByRole("heading", { name: "분석 이력" })).toBeVisible();
    await expect(page.getByText("완료").first()).toBeVisible({ timeout: 20_000 });
  });
});
