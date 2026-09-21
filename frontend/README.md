This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

---

## 이 프로젝트에서의 프론트엔드

백엔드 API(`docs/규제변화_AI도우미_MD_문서/05_API_명세서.md`)를 소비하는 Next.js 앱.

```bash
pnpm install
cp .env.example .env.local      # 백엔드 주소
pnpm dev                        # http://localhost:3000
```

백엔드가 먼저 떠 있어야 한다: `cd ../backend && .venv/bin/python -m uvicorn app.main:app --port 8000`

### 구조

| 경로 | 책임 |
|---|---|
| `src/lib/schemas.ts` | API 응답 Zod 스키마. 백엔드 계약을 런타임에 검증한다 |
| `src/lib/api.ts` | API 클라이언트. 에러 봉투를 `ApiError`로 변환 |
| `src/lib/display.ts` | 판정·행동등급의 색과 문구를 한 곳에서 정의 |
| `src/hooks/` | 서버 상태 (TanStack Query) |
| `src/app/onboarding` | 프로필 입력. `GET /profile` 404가 여기로 보내는 신호다 |
| `src/app/dashboard` | 분석 실행·폴링, ACTION 우선 정렬 |
| `src/app/results/[id]` | 상세 + 근거 3분리 |

### E2E 테스트 (NFR-010)

```bash
# 백엔드와 프론트가 떠 있어야 한다
pnpm e2e          # 13개, 약 33초
pnpm e2e:ui       # UI 모드
```

`00-preflight`가 먼저 돌아 "코드가 틀렸나, 서버가 안 떴나"를 구분해 준다.
여정 테스트는 **분석을 한 번만 실행하고 이어서 검증한다** — 테스트마다 분석을
돌리면 매번 법제처 조회와 조문별 LLM 호출이라 수 분이 걸리고, 사용자당 진행 중인
분석이 하나뿐이라는 제약(FR-003)과도 부딪힌다.

### 설계 원칙

1. **응답을 믿지 않고 검증한다.** `as` 캐스팅 대신 Zod로 파싱한다. 백엔드 계약이
   바뀌면 화면이 undefined로 조용히 깨지는 대신 어디가 어긋났는지 즉시 드러난다.
2. **근거를 섞지 않는다.** `LegalEvidence` / `ReferenceEvidence` / `AiInterpretation`이
   별도 타입이고, 상세 화면에서 배지로 구분해 표시한다 (AP-05).
3. **빈 화면을 만들지 않는다.** 로딩·실패·빈 결과·보류 모두 무엇이 일어났고
   다음에 뭘 하면 되는지 말한다 (NFR-013).
