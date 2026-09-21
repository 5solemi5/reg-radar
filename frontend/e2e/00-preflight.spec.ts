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
    expect(
      health.pending_migrations,
      "적용되지 않은 마이그레이션이 있습니다. `python scripts/migrate.py`를 실행하세요.",
    ).toEqual([]);
  });

  test("백엔드가 프론트엔드와 같은 버전이다", async ({ request }) => {
    /**
     * 낡은 백엔드 프로세스를 그냥 테스트하는 일을 막는다.
     *
     * 실제로 겪었다. 백엔드를 고치고 E2E를 돌렸는데, 몇 시간 전에 띄운
     * 프로세스가 그대로 살아 있어 새 엔드포인트를 모르는 채로 테스트가
     * 돌았다. 그때는 응답 스키마도 함께 바뀌어 Zod가 잡아 줬지만, 동작만
     * 바뀌었다면 낡은 코드를 통과시키고 초록불이 떴을 것이다.
     *
     * 프론트엔드가 호출하는 엔드포인트가 실제로 있는지 확인한다. 완벽한
     * 버전 대조는 아니지만, '언제 띄웠는지 모르는 프로세스'를 거르는 데는
     * 충분하고 유지 비용이 거의 없다.
     */
    const base =
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

    const response = await request.get(`${base}/profile/activities`);
    expect(
      response.status(),
      "백엔드가 /profile/activities를 모릅니다. 변경 전에 띄운 프로세스일 수 있으니 재시작하세요.",
    ).toBe(200);

    const body = await response.json();
    expect(
      body.items.length,
      "사업 활동 질문이 비어 있습니다. 온보딩이 질문을 그릴 수 없습니다.",
    ).toBeGreaterThan(0);
  });
});
