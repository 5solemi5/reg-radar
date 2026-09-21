**규제 변화 감지 · 직무별 대응안 생성 AI 도우미**

# 05. API 명세서

FastAPI 백엔드(W2)가 실제로 노출하는 HTTP 계약을 정의한다. 이 문서는 설계안이
아니라 **구현된 동작의 기록**이며, 코드와 어긋나면 코드가 기준이다.

문서 상태: W2 구현 완료 기준 · 작성 기준일: 2026-09-21
상위 문서: 03 요구사항 정의서 / 04 시스템 아키텍처 설계서
구현 위치: `backend/app/api/` · 대화형 문서: 서버 기동 후 `/docs`

Base URL: `/api/v1`

---

## 1. 이 API가 지키는 약속

### 1-1. 근거는 섞이지 않는다 (AP-05, FR-014)

결과·근거 응답은 네 블록을 **별도 키**로 내보낸다.

| 키 | 성격 | 출처 |
|---|---|---|
| `legal_evidence` | 법적 근거 (모법) | 법제처 원문. 모델이 생성하지 않는다 |
| `delegated_evidence` | 법적 근거 (하위법령) | 모법이 위임한 시행령·시행규칙 원문 (ADR-025) |
| `reference_evidence` | 참고 자료 | RAG 검색 결과. 법적 권위 없음 |
| `ai_interpretation` | AI 해석 | LLM 출력 중 Validator를 통과한 것 |

프론트가 이들을 섞어 렌더링하려면 의도적으로 합쳐야 한다. 응답만 봐도 무엇이
공식 원문이고 무엇이 해석인지 구분된다.

**`legal_evidence`와 `delegated_evidence`를 왜 나누는가.** 둘 다 법제처 원문이지만
서로 다른 법령이다. 한 배열에 담으면 사용자가 시행령 구절을 모법 조문 원문에서
찾으려다 실패한다. 근거는 어디서 확인할 수 있는지까지가 근거다 (BR-001).

`ai_interpretation`에는 `law_name`, `article_no`, `effective_date`, `ministry`,
`source_url` 필드가 **존재하지 않는다.** 담을 자리가 없으므로 위조도 불가능하다 (FR-020).

### 1-2. 검증된 인용만 나간다 (FR-021, FR-022)

`legal_evidence.quoted_spans`에는 **원문에 실제로 존재함이 확인된 인용만** 담긴다.
확인되지 않은 인용은 제거되며, 제거된 개수는 `validation.dropped_span_count`로
드러난다. 검증에 실패한 결과(`status=REJECTED`)는 기본 응답에서 제외된다.

### 1-3. 실패를 성공으로 위장하지 않는다 (NFR-005)

분석 실패는 `status=FAILED`와 사용자용 `error` 문구로 명시된다. 부분 실패(법령 일부
조회 실패)도 집계에 그대로 드러난다.

### 1-4. 남의 데이터는 404다 (NFR-007)

다른 사용자의 리소스에 접근하면 403이 아니라 **404**를 반환한다. 존재 여부조차
알려주지 않기 위해서다.

---

## 2. 인증

| 모드 | 방식 | 용도 |
|---|---|---|
| `AUTH_MODE=supabase` | `Authorization: Bearer <Supabase JWT>` | 운영 |
| `AUTH_MODE=dev` | `X-User-Id` 헤더 | **로컬 개발 전용** |

Supabase 모드는 토큰 헤더의 알고리즘에 따라 검증 방식을 고른다.

- **ES256 / RS256** — 프로젝트의 JWKS에서 `kid`에 맞는 공개키를 받아 검증한다.
  Supabase의 현재 기본값이다. 공개키를 못 받으면 통과시키지 않고 실패시킨다.
- **HS256** — `SUPABASE_JWT_SECRET`으로 검증한다. 레거시 키를 쓰는 프로젝트용.

어느 쪽이든 서명·만료·`audience=authenticated`·`sub` 존재를 모두 확인하고,
허용 알고리즘을 고정한다 (토큰이 알고리즘을 고르게 두면 `alg:none` 공격에 열린다).
만료된 토큰은 다른 실패와 구분해 "세션이 만료되었습니다"로 응답한다.

`APP_ENV=production`과 `AUTH_MODE=dev`를 함께 쓰면 애플리케이션이 기동을 거부한다.
dev 모드는 헤더를 그대로 신뢰하므로 운영에서는 인증이 없는 것과 같기 때문이다.

라우터는 `CurrentUser`에만 의존하므로 W4 교체가 라우터 코드로 번지지 않는다.

---

## 3. 공통 에러 계약

모든 에러는 동일한 봉투로 나간다. 프론트는 한 가지 형태만 다루면 된다.

```json
{
  "error": {
    "code": "profile_required",
    "message": "분석을 실행하려면 먼저 업무 프로필을 입력해야 합니다.",
    "detail": null
  }
}
```

| code | HTTP | 의미 | 대응 요구사항 |
|---|---|---|---|
| `unauthorized` | 401 | 인증 누락/만료 | ER-007 |
| `not_found` | 404 | 리소스 없음 **또는 타인 소유** | NFR-007 |
| `profile_required` | 409 | 프로필 미설정 상태에서 분석 시도 | ER-006 |
| `analysis_in_progress` | 409 | 이미 진행 중인 분석 존재 | FR-003 |
| `validation_rejected` | 422 | Validator 차단 | ER-004 |
| `upstream_unavailable` | 503 | 법제처·LLM 등 외부 실패 | ER-001, ER-002 |
| `internal_error` | 500 | 그 외 | — |

요청 본문 스키마 위반은 FastAPI 기본 422로 응답한다. 모든 입력 스키마는
`extra="forbid"`이므로 **정의되지 않은 필드를 보내면 거부**된다.

---

## 4. Endpoint

### 4-1. 시스템

#### `GET /health`

설정 상태를 보고한다. **키 값 자체는 절대 응답에 포함하지 않는다** (NFR-008).

```json
{
  "status": "ok", "env": "local", "auth_mode": "supabase",
  "storage": "postgres", "database_connected": true,
  "rag_enabled": true, "rag_indexed_chunks": 184,
  "law_api_configured": true, "llm_configured": true, "llm_model": "gpt-4o"
}
```

`rag_indexed_chunks`를 노출하는 이유: 참고자료 0건은 정상 상태로 처리되므로
(BR-005), 인덱스가 비어 있다는 설정 실수가 조용히 묻힌다. 배포 후 이 값이
0이면 `scripts/ingest_rag.py`를 돌리지 않은 것이다.

### 4-2. 프로필 (FR-002, UC-01)

#### `GET /profile`

| 응답 | 의미 |
|---|---|
| `200` | 프로필 반환 |
| `404` | **프로필 미설정 — 프론트는 이 신호로 온보딩을 먼저 띄운다** |

#### `PUT /profile` — 생성 또는 전체 교체

```json
{
  "job": "HR 담당자 (채용·근태·취업규칙)",
  "industry": "IT 서비스",
  "company_size": "MEDIUM",
  "employee_count": 80,
  "interests": ["노동", "근로계약"]
}
```

| 필드 | 필수 | 비고 |
|---|---|---|
| `job` | ✔ | 1~100자. 공백만 입력 불가 |
| `industry` | ✔ | 1~100자 |
| `company_size` | ✔ | `SOLO` \| `MICRO` \| `SMALL` \| `MEDIUM` \| `LARGE` |
| `employee_count` | — | 0 이상. **null 허용이며 그 경우 규모 조건에서 보류가 난다** |
| `interests` | — | 최대 20개 |

재저장해도 `created_at`은 유지된다.

#### `PATCH /profile` — 부분 수정

보낸 필드만 바꾼다. 프로필이 없으면 `404`.

프로필을 바꿔도 **기존 분석 이력은 당시 기준으로 보존된다** (FR-002 AC, BR-006).

### 4-3. 분석 (FR-003, UC-02)

#### `POST /analyses` → `202 Accepted`

```json
{ "period_from": "2026-06-01", "period_to": "2026-09-21",
  "law_query": "근로기준법", "max_laws": 3 }
```

모든 필드가 선택이다.

**분석 대상 선정 (ADR-015):**
- `law_query`가 있으면 그 법령만 본다.
- 없으면 **프로필의 관심 영역과 업종을 법령명 검색어로 바꿔** 후보를 고른다.
  (예: 관심영역 `노동·인사` → `근로기준법`, `최저임금법` … / 업종 `이커머스` → `전자상거래`)
  검색어당 대표 법령 1건씩만 담아 특정 영역이 후보를 독식하지 않게 한다.
- 관심 영역·업종에서 아무것도 안 걸리면 기본 후보(근로기준법·개인정보 보호법·
  산업안전보건법)를 쓴다. 그래도 없으면 시행일 범위 최신순으로 되돌아간다.
- 기간을 지정하지 않으면 최근 180일이 기본이다.

**분석량 상한 (ADR-016):** 조문 1건이 LLM 3회를 쓰므로, 분석 1회당 법령 3건·
조문 12건을 넘지 않는다. 법령을 번갈아 가며 조문을 뽑아 한 법령이 상한을
독식하지 않게 한다. 조문 분석은 동시성 4로 실행된다.

**즉시 202와 `analysis_id`를 반환하고 분석은 백그라운드에서 돈다.** 분석 1건은
법령 조회와 조문별 LLM 호출로 수십 초가 걸린다(실측: 법령 1건 16초, 법령 3건·
조문 12건 42초). 동기 응답으로 묶으면 NFR-006(장시간 무응답 UI 금지)을 위반한다.

| 응답 | 의미 |
|---|---|
| `202` | 접수됨. `analysis_id`로 폴링 |
| `409 profile_required` | 프로필 미설정 |
| `409 analysis_in_progress` | 진행 중인 분석 존재. `detail`에 기존 `analysis_id` |

#### `GET /analyses/{id}` — 상태 폴링

```json
{
  "analysis_id": "94e1e6a0-...", "status": "COMPLETED",
  "created_at": "...", "started_at": "...", "completed_at": "...",
  "laws_examined": 1, "articles_changed": 1,
  "counts": { "action": 0, "decision": 0, "awareness": 1,
              "hold": 0, "not_applicable": 0, "rejected": 0, "total": 1 },
  "error": null, "trace_id": "..."
}
```

`status`: `CREATED` → `RUNNING` → `COMPLETED` | `FAILED` (04 설계서 §10-1).
프론트는 `COMPLETED`/`FAILED`가 될 때까지 폴링한다.

#### `GET /analyses` — 히스토리 (FR-018)

`limit`(1~100, 기본 20), `offset`. 최신순. 응답은 `{items, total, limit, offset}`.

#### `DELETE /analyses/{id}` → `204`

진행 중인 분석을 `FAILED`로 표시한다. 멈춘 분석이 새 실행을 영구히 막는 것을 방지한다.

#### `GET /analyses/{id}/results` — 결과 목록 (FR-015, FR-016)

| 쿼리 | 기본 | 의미 |
|---|---|---|
| `include_not_applicable` | `false` | 무관 항목 포함 여부 |
| `include_rejected` | `false` | 검증 실패 결과 포함 여부 |

**정렬은 고정이다:** 해당(ACTION → DECISION → AWARENESS) → 보류 → 무관.
사용자가 “지금 할 일”을 먼저 보게 하기 위해서다.

무관·검증실패 항목은 기본 응답에서 빠진다. 요청해야 보인다.

### 4-4. 결과와 근거 (FR-012~014, FR-016)

#### `GET /results/{id}` — 규제 상세

```json
{
  "result_id": "...", "status": "VALIDATED",
  "applicability": "APPLICABLE", "action_grade": "AWARENESS",
  "change": { "change_type": "AMENDED",
              "additions": ["제19조에 따른"], "deletions": ["제19조제1항에 따른"],
              "delegation_targets": [] },
  "legal_evidence": { "law_name": "근로기준법", "article_no": "제60조",
                      "article_title": "연차 유급휴가",
                      "effective_date": "2026-08-20", "ministry": "고용노동부",
                      "source_url": "...", "quoted_spans": ["..."] },
  "delegated_evidence": [
    { "law_name": "근로기준법 시행령", "law_type": "대통령령",
      "article_no": "제33조", "article_title": "연차 유급휴가의 사용촉진",
      "source_url": "...", "quoted_spans": ["..."], "resolves_criterion": true }
  ],
  "reference_evidence": [],
  "ai_interpretation": { "reason": "...", "matched_conditions": [],
                         "missing_context": [], "impact_summary": "...",
                         "affected_work": [], "checklist": [],
                         "confidence": 0.9, "model": "gpt-4o" },
  "validation": { "passed": true, "checks": {...}, "failures": [],
                  "dropped_span_count": 0 }
}
```

**`applicability`와 `action_grade`는 다른 축이다** (BR-007).
보류·무관 결과의 `action_grade`는 `null`이다. 보류는 행동 등급 확정보다 보류 사유
해소가 먼저이기 때문이다 (FR-010).

#### `GET /results/{id}/evidence` — 근거 조회

`legal_evidence` / `delegated_evidence` / `reference_evidence` / `ai_interpretation`을
분리해 반환하며, `disclaimer`로 **법률 자문이 아님**을 명시한다 (NFR-015).

`delegated_evidence`는 모법 조문이 "대통령령으로 정한다"로 위임한 하위법령 조문 중
**판정 근거로 실제 인용된 것**만 담는다 (ADR-025). 붙였다는 이유만으로 전부 넣으면
판정과 무관한 조문까지 법적 근거로 제시하게 된다.

`resolves_criterion: false`는 그 조문이 기준을 다시 별표 등으로 넘긴다는 뜻이다.
이 경우 기준 자체는 확보되지 않았으므로 판정은 보류로 남는다 (ADR-027).

`reference_evidence`는 법제처 법령해석례·행정규칙·판례에서 검색된 실무 맥락이다
(07. RAG 설계서). **빈 배열일 수 있고 그것은 오류가 아니다** — 조문만으로
판단했다는 뜻이며, 모델이 없는 출처를 지어내지 않았다는 뜻이다 (BR-005).

`RAG_ENABLED=false`이거나 인덱스가 비어 있으면 항상 빈 배열이다.

### 4-5. 보류 재판정 (FR-008, BR-008)

#### `POST /results/{id}/reassess` → `201`

보류 결과에 부족한 정보를 채워 **그 조문만** 다시 판단한다. 분석 전체를 다시
돌릴 이유가 없다.

```json
{ "employee_count": 80, "notes": "우리는 제조업이 아닙니다", "apply_to_profile": true }
```

| 필드 | 비고 |
|---|---|
| `employee_count` | 가장 흔한 보류 사유. 규모 기준 판정에 쓰인다 |
| `notes` | 그 밖에 판단에 필요한 정보 (최대 500자) |
| `apply_to_profile` | 입력한 인원 수를 프로필에도 저장할지 |

**기존 결과를 덮어쓰지 않는다.** 새 결과를 만들고 이력으로 연결하므로 판정이
왜 바뀌었는지 추적할 수 있다 (BR-008). 두 결과 모두 조회 가능하다.

**분석 당시 법령 근거로 재판정한다.** `law_snapshots`에 보존된 원문과 최초
분석의 변경 내용을 그대로 쓴다 (AP-07, BR-006). 신구법을 다시 부르면 그 사이
또 개정됐을 때 다른 근거로 판단하게 된다.

응답:

```json
{
  "revision_id": "...", "original_result_id": "...",
  "previous_applicability": "HOLD", "new_applicability": "APPLICABLE",
  "changed": true,
  "message": "HOLD → APPLICABLE로 바뀌었습니다.",
  "added_context": { "상시근로자 수": "80" },
  "result": { ... }
}
```

| 응답 | 의미 |
|---|---|
| `201` | 재판정 완료. `changed`로 판정이 바뀌었는지 확인 |
| `404` | 결과 없음 또는 타인 소유 |
| `409 profile_required` | 프로필 미설정 |
| `409 reassess_not_allowed` | 보류 상태가 아니거나, 추가 정보가 비었거나, 법령 근거 없음 |

`apply_to_profile`은 **재판정이 성공한 뒤에** 반영한다. 실패했는데 프로필만
바뀌면 사용자가 무엇이 적용됐는지 알 수 없다.

#### `GET /results/{id}/revisions`

이 결과와 연결된 재판정 이력. 어떤 정보를 채워서 판정이 어떻게 바뀌었는지 남는다.

### 4-6. 피드백·저장

| Endpoint | 역할 | 요구사항 |
|---|---|---|
| `POST /results/{id}/feedback` | `{helpful, correction_type?, comment?}` → `201` | FR-019 |
| `POST /saved-regulations` | `{result_id, note?}` → `201`. 법령 정보를 함께 기록 | FR-017 |
| `GET /saved-regulations` | 최신순 목록 | FR-017 |
| `DELETE /saved-regulations/{id}` | `204` | FR-017 |

---

## 5. 프론트엔드 연동 흐름

```
1. GET /profile
     └ 404 → Onboarding으로 이동
     └ 200 → Dashboard

2. POST /analyses            → 202 { analysis_id }
3. GET  /analyses/{id}       → 폴링 (RUNNING → COMPLETED)
4. GET  /analyses/{id}/results  → 대시보드 카드
5. GET  /results/{id}        → 상세 화면
6. GET  /results/{id}/evidence  → Evidence 탭
7. POST /results/{id}/reassess  → 보류 해소 (선택)
8. POST /saved-regulations, /results/{id}/feedback
```

### 5-1. 상태별 UI 대응 (03 요구사항 §5-2)

| 상태 | 신호 | 화면 |
|---|---|---|
| 분석 진행 중 | `status=RUNNING` | 진행 표시. 빈 화면 금지 |
| 분석 실패 | `status=FAILED` + `error` | 재시도 버튼 + 사유 |
| 해당 | `applicability=APPLICABLE` | 행동등급 + 근거 + 원문 링크 |
| 보류 | `applicability=HOLD` | `missing_context`를 **입력 유도 문구**로 노출 |
| 무관 | `applicability=NOT_APPLICABLE` | 기본 접기 |
| 근거 불완전 | `dropped_span_count > 0` | 일부 인용이 검증에서 제외됐음을 표시 |

`missing_context`는 “사용자가 값을 하나 더 넣으면 풀리는 것”만 담기도록 설계되어
있다. 화면에서 그대로 입력 폼으로 연결할 수 있다.

---

## 6. 아직 없는 것

| 항목 | 상태 | 예정 |
|---|---|---|
| 분석 이력 비교 (UC-11) | 미구현 | W6 |

---

규제 변화 감지 · 직무별 대응안 생성 AI 도우미
05. API 명세서 · 2026-09-21
기준 문서: 03. 요구사항 정의서 / 04. 시스템 아키텍처 설계서
