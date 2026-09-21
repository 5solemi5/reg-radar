# 규제 변화 AI 도우미 — Backend / AI Core

문서 `docs/규제변화_AI도우미_MD_문서/` 기준 구현. 현재 단계는 **W1: AI Core & Legal Data**.

## 실행 준비

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
cp .env.example .env     # LAW_API_OC, OPENAI_API_KEY 입력
```

`LAW_API_OC`는 [open.law.go.kr](https://open.law.go.kr) 가입 이메일의 `@` 앞부분입니다.

## 테스트

```bash
.venv/bin/python -m pytest -q                            # 전체 (116)
.venv/bin/python scripts/run_eval.py --save              # Q1~Q6 실측
.venv/bin/python scripts/smoke_law_api.py "근로기준법"    # 법제처 실연결 확인
.venv/bin/python scripts/smoke_change_analysis.py 근로기준법   # 실제 개정 기반 E2E
.venv/bin/python scripts/smoke_analysis.py 근로기준법 제93조   # 프로필 비교 (조문 지정)
```

- `smoke_change_analysis.py`: 법제처가 **이번 개정에서 바뀌었다고 표시한 조문만**
  분석합니다. 근로기준법 기준 132개 조문 중 1건입니다.
- `smoke_analysis.py`: 지정한 조문에 세 프로필을 넣어 **무관 / 해당 / 보류**로
  갈리는지 봅니다 (기획서 §13 '입력 비교' 장면). 개정 전 텍스트는 시뮬레이션입니다.

## 디렉터리 구조

| 경로 | 책임 | 관련 원칙 |
|---|---|---|
| `app/core/` | 설정. secret은 환경변수로만 | NFR-008 |
| `app/domain/context.py` | LLM **입력** Context (User/Legal/Change/Rag) | AP-06 |
| `app/domain/outputs.py` | LLM **출력** 스키마. 공식 사실 필드 자체가 없음 | FR-020 |
| `app/domain/result.py` | 최종 결과. 법적근거/참고자료/AI해석 필드 분리 | AP-05, FR-014 |
| `app/adapters/law/` | 법제처 OPEN API — 공식 사실값의 유일한 공급원 | AP-01, BR-001 |
| `app/adapters/law/oldnew.py` | 신구법 비교 — 변경 조문·변경 구간의 공식 원천 | FR-005 |
| `app/diff/engine.py` | 신구법 diff + 하위법령 위임 감지. 전부 코드 | BR-002, Q5 |
| `app/diff/headcount.py` | 상시근로자 수 기준 충족 판정. 산술은 코드가 | AP-03 |
| `app/ai/llm.py` | LLM provider 추상화 | NFR-012 |
| `app/ai/context_builder.py` | 입력 packet 렌더링 | AP-06 |
| `app/ai/chains/` | C3 추출 → C4 매핑 → C5 영향 | AP-02 |
| `app/validator/` | C6. 인용·금지필드·HOLD 검증 | FR-020~022 |
| `app/services/analysis_service.py` | C3~C6 orchestration + 결과 조립 | 04 §5-2 |
| `app/api/` | FastAPI 라우터·스키마·인증·에러 계약 | AP-06, ER-001~008 |
| `app/repositories/` | 저장소 Protocol + 인메모리/Postgres 구현 | NFR-011 |
| `migrations/` | DB 스키마·RLS. 도메인 규칙을 제약으로 이중화 | BR-003, BR-007, FR-003 |
| `app/services/analysis_runner.py` | 분석 orchestration: 수집 → 분석 → 저장 | 04 §5-2 |
| `app/rag/` | 참고자료 수집·청킹·임베딩·검색 | FR-013, BR-004~005 |
| `app/repositories/traces.py` | AI 실행 추적. 프롬프트 원문은 저장하지 않는다 | NFR-009 |
| `evaluation/` | 평가 데이터셋·지표·리포트 ([README](evaluation/README.md)) | 기획서 §11 |

## 설계상 지켜지는 불변식

1. **법령 사실값은 LLM이 만들 수 없다.** `ApplicabilityOutput` / `ImpactOutput` 스키마에
   `law_name`, `article_no`, `effective_date` 같은 필드가 아예 존재하지 않는다.
   `assert_no_forbidden_fields()`가 이를 테스트에서 강제한다.
2. **변화는 모델이 만들지 않는다.** 법제처 신구법 비교가 `<P>` 태그로 표시한 구간을
   그대로 쓰고(`change_from_official_marks`), 그 응답을 못 받을 때만 텍스트 비교로
   추정한다(`compute_change`). 어느 쪽이든 모델은 여기 없는 변화를 말할 수 없다.
3. **불확실하면 HOLD.** `ApplicabilityOutput`은 HOLD인데 `missing_context`가 비면
   스키마 단계에서 거부된다.
4. **근거는 섞이지 않는다.** `LegalEvidence` / `ReferenceEvidence` / `AiInterpretation`이
   별도 타입이라 데이터 모델 수준에서 혼합이 불가능하다.
5. **산술은 LLM에 맡기지 않는다.** "상시 10명 이상" 같은 규모 기준 충족 여부는
   `app/diff/headcount.py`가 계산해 사실로 주입한다. 첫 E2E에서 LLM이 이 판단을
   '용어 정의가 불명확하다'며 회피해 세 프로필이 전부 보류로 나온 회귀가 있었다.
6. **근거 없는 '해당'은 차단된다.** 검증된 인용이 하나도 남지 않은 APPLICABLE은
   Validator가 REJECT한다 — 이 서비스에서 가장 위험한 출력이기 때문이다 (Q2).

## API 실행

```bash
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
open http://127.0.0.1:8000/docs
.venv/bin/python scripts/smoke_api.py http://127.0.0.1:8000/api/v1   # E2E 확인
```

| Method | Endpoint | 역할 |
|---|---|---|
| GET | `/api/v1/health` | 설정 상태 (키 값은 노출하지 않음) |
| GET/PUT/PATCH | `/api/v1/profile` | 업무 프로필. 없으면 404 → 온보딩 |
| POST | `/api/v1/analyses` | 분석 시작. **202**를 즉시 반환하고 백그라운드 실행 |
| GET | `/api/v1/analyses` | 분석 히스토리 (최신순, 페이지네이션) |
| GET | `/api/v1/analyses/{id}` | 분석 상태 폴링 |
| GET | `/api/v1/analyses/{id}/results` | 결과 목록. ACTION·DECISION 우선 정렬 |
| GET | `/api/v1/results/{id}` | 규제 상세 |
| GET | `/api/v1/results/{id}/evidence` | 근거 — 세 종류 분리 |
| POST | `/api/v1/results/{id}/feedback` | 판정 피드백 |
| GET/POST/DELETE | `/api/v1/saved-regulations` | 관심 규제 저장 |

분석은 법령 조회와 조문별 LLM 호출 때문에 수십 초가 걸린다. 동기 응답으로 묶으면
NFR-006(장시간 무응답 UI 금지)을 어기므로, 202로 `analysis_id`를 먼저 주고
프론트가 상태를 폴링하는 구조다.

### 저장소

```bash
# 인메모리 (기본) — 재시작 시 소실
.venv/bin/python -m uvicorn app.main:app --port 8000

# Postgres
createdb regradar
psql -d regradar -f migrations/001_initial_schema.sql
STORAGE=postgres DATABASE_URL=postgresql://127.0.0.1:5432/regradar \
  .venv/bin/python -m uvicorn app.main:app --port 8000
```

Supabase도 Postgres이므로 같은 마이그레이션을 쓴다. 상세는
`docs/규제변화_AI도우미_MD_문서/06_데이터_모델_ERD.md`.

### 인증

| 모드 | 방식 | 용도 |
|---|---|---|
| `AUTH_MODE=dev` | `X-User-Id` 헤더 | 로컬 전용 |
| `AUTH_MODE=supabase` | `Authorization: Bearer <JWT>` | 운영 |

`APP_ENV=production` + `AUTH_MODE=dev` 조합은 앱 기동 자체를 거부한다 — dev 모드는
헤더를 그대로 믿으므로 운영에서는 인증이 없는 것과 같다.

### 참고자료(RAG) 인덱스

```bash
.venv/bin/python scripts/ingest_rag.py            # 기본 검색어로 수집·색인
.venv/bin/python scripts/ingest_rag.py --status   # 인덱스 현황
```

법제처의 법령해석례(`expc`)·행정규칙(`admrul`)·판례(`prec`)를 수집한다. 정부
사이트를 스크래핑하지 않는 이유와 검색 설계는
`docs/규제변화_AI도우미_MD_문서/07_RAG_설계서.md` 참조.

`RAG_ENABLED=false`(기본값)이면 참고자료 없이 동작한다. **참고자료 없음은
오류가 아니라 정상 상태다** (BR-005).

### 관측성 (NFR-009)

```bash
.venv/bin/python scripts/trace_report.py            # 최근 분석
.venv/bin/python scripts/trace_report.py --chains   # 체인별 토큰·지연
.venv/bin/python scripts/trace_report.py --failures # 실패한 호출
```

체인 호출 단위로 latency·model·input/output 토큰·실패를 `ai_traces`에 남긴다.
**프롬프트 원문과 모델 응답 전문은 저장하지 않는다** — 사용자 프로필과 법령
원문이 그대로 남으면 관측성 도구가 개인정보 저장소가 된다.

### 저장소 테스트

`tests/test_repositories.py`는 **같은 테스트를 인메모리와 Postgres 양쪽에** 돌린다.
구현마다 다른 테스트를 쓰면 미묘한 동작 차이가 숨는다. Postgres가 없으면 해당
케이스는 사유를 밝히고 건너뛴다.

```bash
createdb regradar_test
psql -d regradar_test -f migrations/001_initial_schema.sql
.venv/bin/python -m pytest tests/test_repositories.py -q
```

## 평가 실측 (2026-09-21 · 15케이스)

| 지표 | 목표 | gpt-4o | gpt-4o-mini |
|---|---|---|---|
| 판정 정확도 | — | **100%** | 86.7% |
| Q2 오탐률 | ≤ 5% | 0% | 0% |
| Q4 재현율 | ≥ 90% | 100% | 60% ✗ |
| Q6 금지 필드 유출 | 0건 | 0건 | 0건 |

기본 모델이 `gpt-4o`인 이유는 gpt-4o-mini가 Q4 재현율 60%로 NFR-003을 충족하지
못했기 때문이다. 수치를 읽는 법과 과적합 주의사항은 `evaluation/README.md` 참조.

## 분석 후보를 어떻게 정하는가

"최근 규제 변화를 분석한다"는 말은 구체적으로 **직전 개정에서 실제로 바뀐 조문만**
분석한다는 뜻이다. 법제처 신구법 비교(`target=oldAndNew`)가 변경된 조문만 돌려주고,
바뀐 구간은 `<P>` 태그로 직접 표시해 준다.

근로기준법의 경우 전체 132개 조문 중 이번 개정(2025-10-01 → 2026-08-20)에서 바뀐
조문은 **제60조 1건**이며, 변경 내용은 `"제19조제1항에 따른"` → `"제19조에 따른"`이다.
전 조문을 LLM에 넣는 대신 이 1건만 분석하면 되므로 비용과 정확도가 함께 해결된다.
