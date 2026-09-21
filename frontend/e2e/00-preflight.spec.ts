import { expect, test } from "@playwright/test";

/**
 * 사전 점검.
 *
 * 나머지 테스트가 실패했을 때 "코드가 틀렸나, 서버가 안 떴나"를 구분하기 위해
 * 가장 먼저 돈다. 실패 메시지가 무엇을 띄워야 하는지 알려준다.
 */
test.describe("사전 점검", () => {
  test("프론트엔드가 떠 있다", async ({ page }) => {
    const response = await page.goto("/");
    expect(
      response?.status(),
      "프론트엔드가 응답하지 않습니다. `pnpm dev`로 띄우세요.",
    ).toBeLessThan(400);
  });

  test("백엔드가 떠 있고 설정이 되어 있다", async ({ request }) => {
    const base =
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

    let response;
    try {
      response = await request.get(`${base}/health`);
    } catch {
      throw new Error(
        `백엔드(${base})에 연결할 수 없습니다. ` +
          "backend에서 `uvicorn app.main:app --port 8000`로 띄우세요.",
      );
    }

    expect(response.ok()).toBeTruthy();
    const health = await response.json();
    expect(health.status).toBe("ok");
    expect(
      health.law_api_configured,
      "LAW_API_OC가 설정되지 않았습니다.",
    ).toBeTruthy();
    expect(health.llm_configured, "OPENAI_API_KEY가 설정되지 않았습니다.").toBeTruthy();
  });
});
