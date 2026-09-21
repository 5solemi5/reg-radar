import { defineConfig, devices } from "@playwright/test";
import { config as loadEnv } from "dotenv";

// 테스트 계정 정보는 저장소에 두지 않는다.
loadEnv({ path: ".env.e2e.local", quiet: true });
loadEnv({ path: ".env.local", quiet: true });

/**
 * E2E 설정 (NFR-010).
 *
 * 백엔드와 프론트가 모두 떠 있어야 한다. 서버를 자동으로 띄우지 않는 이유는,
 * 백엔드가 실제 법제처·LLM·DB에 붙어 있어 기동 조건이 환경마다 다르기 때문이다.
 * 대신 사전 점검 테스트가 무엇이 안 떠 있는지 명확히 알려준다.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // 분석은 사용자당 1건만 동시 실행 가능하다 (FR-003)
  workers: 1,
  retries: 0,
  // 분석 1건이 법령 조회 + 조문별 LLM 호출이라 수십 초 걸린다.
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "ko-KR",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
