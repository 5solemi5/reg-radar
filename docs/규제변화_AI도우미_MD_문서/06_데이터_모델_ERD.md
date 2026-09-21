**규제 변화 감지 · 직무별 대응안 생성 AI 도우미**

# 06. 데이터 모델 / ERD

기획서 §9의 도메인 테이블을 실제 DB 스키마로 정의한다. 이 문서는 설계안이 아니라
**적용된 스키마의 기록**이며, `backend/migrations/001_initial_schema.sql`이 기준이다.

문서 상태: W4 구현 완료 기준 · 작성 기준일: 2026-09-21
상위 문서: 03 요구사항 정의서 / 04 시스템 아키텍처 설계서
구현 위치: `backend/migrations/` · `backend/app/repositories/postgres.py`

---

## 1. 설계 원칙

### 1-1. 도메인 규칙을 DB가 한 번 더 막는다

애플리케이션은 이미 스키마(Pydantic)와 Validator로 규칙을 강제한다. DB 제약은
그 코드가 뚫렸을 때를 위한 두 번째 층이다. 특히 동시 요청이 겹치면 코드만으로는
막을 수 없는 것들이 있다.

| 제약 | 강제하는 규칙 | 근거 |
|---|---|---|
| `action_grade_only_when_applicable` | 보류·무관에는 행동 등급을 부여하지 않는다 | BR-007, FR-010 |
| `hold_requires_missing_context` | 보류는 무엇이 부족한지 반드시 말해야 한다 | BR-003 |
| `uq_analyses_one_active_per_user` | 사용자당 진행 중인 분석은 하나만 | FR-003 |
| `ai_confidence BETWEEN 0 AND 1` | 확신도 범위 | — |
| `profiles` job/industry CHECK | 공백만 입력 불가 | FR-002 |

### 1-2. 사용자 데이터 격리는 컬럼으로 (NFR-007)

`analysis_results`는 `analysis_id`로 소유자를 알 수 있는데도 `user_id`를 따로 둔다.
결과 단건 조회에서 조인 없이 격리를 확인하기 위해서다. 조인을 잊으면 남의 데이터가
새지만, 컬럼이 있으면 `WHERE user_id = $2`를 빠뜨렸을 때 결과가 비어 바로 드러난다.

### 1-3. 분석 당시 근거를 보존한다 (AP-07, BR-006)

`law_snapshots`는 분석 시점의 법령 원문을 통째로 저장한다. 법령은 계속 개정되므로,
과거 분석을 재현하려면 그때의 원문이 남아 있어야 한다. `(law_id, mst)`로 식별해
같은 법령의 다른 개정 버전이 각각 보존된다.

`analysis_results`도 법령명·조문번호·시행일을 **비정규화해 복사**한다. snapshot을
참조만 하면 조회마다 조인이 필요하고, 무엇보다 "그때 사용자가 본 값"이 지금
snapshot과 다를 수 있다.

---

## 2. ERD

```
                    ┌─────────────┐
                    │  profiles   │  user_id (PK)
                    │             │  job, industry, company_size,
                    │             │  employee_count, interests[]
                    └─────────────┘
                           ╎ user_id (FK 아님 — Supabase auth.users와 같은 값)
                           ╎
        ┌──────────────────┴───────────────────┐
        │                                      │
┌───────▼────────┐                    ┌────────▼─────────┐
│   analyses     │                    │ saved_regulations│
│ analysis_id PK │                    │ saved_id PK      │
│ user_id        │                    │ user_id          │
│ status         │◄──┐                │ result_id FK ────┼──┐
│ counts jsonb   │   │                │ UNIQUE(user,res) │  │
└───────┬────────┘   │                └──────────────────┘  │
        │ 1:N        │                                      │
┌───────▼─────────────────────┐                             │
│     analysis_results        │◄────────────────────────────┘
│ result_id PK                │
│ analysis_id FK (CASCADE)    │       ┌──────────────┐
│ user_id        ← 격리용      │◄──────┤   feedback   │
│                             │       │ result_id FK │
│ ── 법적 근거 (법제처) ──     │       └──────────────┘
│ law_id, law_name,           │
│ article_no, effective_date, │       ┌──────────────────┐
│ quoted_spans[]              │◄──────┤  hold_revisions  │
│                             │       │ original/new     │
│ ── 변경 (코드/법제처) ──     │       │ result_id FK     │
│ change_type, additions[],   │       └──────────────────┘
│ deletions[], delegation[]   │
│                             │
│ ── AI 해석 ──                │
│ ai_reason, ai_missing_ctx[],│
│ ai_checklist jsonb,         │
│ ai_confidence, ai_model     │
│                             │
│ delegated_evidence jsonb    │  ← 위임 하위법령 (ADR-025)
│ reference_evidence jsonb    │  ← RAG
│ validation jsonb            │
└─────────────────────────────┘

┌──────────────────┐
│  law_snapshots   │  분석 당시 원문 보존 (AP-07)
│ snapshot_id PK   │  UNIQUE(law_id, mst)
│ articles jsonb   │  조문 배열 통째로
└──────────────────┘
```

`law_snapshots`는 `analysis_results`와 FK로 연결하지 않는다. 결과가 이미 필요한
법적 사실을 복사해 갖고 있고, snapshot은 "원문 전체를 다시 보고 싶을 때" 쓰는
별도 자산이기 때문이다. 연결은 `analyses.snapshot_law_ids[]`가 느슨하게 유지한다.

---

## 3. 테이블 상세

### 3-1. `profiles` (FR-002)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| `user_id` | text PK | Supabase `auth.users.id`와 같은 값. 로컬 개발에서는 임의 문자열이 들어오므로 FK를 걸지 않는다 |
| `job`, `industry` | text NOT NULL | 공백만 입력 불가 |
| `company_size` | enum | SOLO / MICRO / SMALL / MEDIUM / LARGE |
| `employee_count` | integer NULL | **NULL이 유효한 상태다.** 규모 조건이 있는 조문에서 보류 사유가 된다 |
| `interests` | text[] | 분석 대상 법령 선정에 쓰인다 (ADR-015) |

`updated_at`은 트리거로 자동 갱신하고, `created_at`은 upsert에서도 유지한다.
프로필을 다시 저장한다고 가입 시점이 바뀌면 안 된다.

### 3-2. `analyses` (FR-003)

`counts`는 결과에서 다시 계산할 수 있지만 jsonb로 비정규화해 둔다. 대시보드가
요약만 보여줄 때 결과 전체를 읽지 않아도 되게 하기 위해서다.

부분 유니크 인덱스가 진행 중인 분석을 하나로 제한한다.

```sql
CREATE UNIQUE INDEX uq_analyses_one_active_per_user
    ON analyses (user_id) WHERE status IN ('CREATED', 'RUNNING');
```

### 3-3. `analysis_results`

**AP-05를 컬럼 구성으로 표현한다.** 법적 근거는 `law_*`·`quoted_spans`,
변경 내용은 `change_*`·`additions`·`deletions`, AI 해석은 `ai_*` 접두사로 묶인다.
`ai_` 컬럼 중 어디에도 법령명·조문번호·시행일이 없다 (FR-020).

`quoted_spans`에는 Validator를 통과한 인용만 들어간다 (FR-021).

### 3-4. 나머지

| 테이블 | 용도 | 비고 |
|---|---|---|
| `law_snapshots` | 분석 당시 원문 | `(law_id, mst)` 유니크 |
| `saved_regulations` | 북마크 (FR-017) | `(user_id, result_id)` 유니크 |
| `feedback` | 품질 피드백 (FR-019) | |
| `hold_revisions` | 보류 재판정 이력 (FR-008, BR-008) | 기존 결과를 덮어쓰지 않고 쌓는다 |

---

## 4. 행 수준 보안 (RLS)

`002_rls_policies.sql` — **Supabase 전용**이다. `auth.uid()`를 쓰므로 로컬
Postgres에서는 적용되지 않는다.

백엔드는 service_role로 연결하며 service_role은 RLS를 우회한다. 즉 이 정책의
목적은 **브라우저가 anon key로 DB에 직접 접근하는 경로를 막는 것**이다. 서버
코드만 믿으면 그 경로가 열려 있다.

`law_snapshots`는 공개 법령 데이터이므로 사용자별 격리 대상이 아니지만, 쓰기는
서버만 할 수 있도록 SELECT 정책만 둔다.

---

## 5. 저장소 교체

`STORAGE` 환경변수로 인메모리와 Postgres를 바꾼다.

| 값 | 용도 |
|---|---|
| `memory` | 로컬 실험. 프로세스 재시작 시 소실 |
| `postgres` | Supabase 또는 로컬 Postgres. `DATABASE_URL` 필요 |

라우터는 어느 쪽인지 모른다. `app/repositories/base.py`의 Protocol만 알면 되고,
`app/api/deps.py`가 설정에 따라 구현을 골라 준다 (NFR-011).

**같은 테스트를 양쪽 구현에 돌린다** (`tests/test_repositories.py`). 구현마다 다른
테스트를 쓰면 미묘한 동작 차이가 숨는다. 실제로 이 방식이 아래 두 문제를 잡았다.

---

## 6. 구현 중 겪은 것

### 6-1. `array_length`는 빈 배열에 NULL을 준다

보류 제약을 처음에 이렇게 썼다.

```sql
CHECK (applicability <> 'HOLD' OR array_length(ai_missing_context, 1) >= 1)
```

빈 배열에 `array_length(arr, 1)`은 `0`이 아니라 **NULL**이고, CHECK 제약은 결과가
NULL이면 **통과**시킨다. 즉 이 제약은 정확히 막아야 할 케이스를 통과시켰다.
`cardinality()`는 빈 배열에 `0`을 주므로 의도대로 동작한다.

스키마를 실제 DB에 적용하고 위반 케이스를 넣어보지 않았다면 발견하지 못했을 버그다.

### 6-2. `real`은 확신도를 왜곡한다

`ai_confidence`를 `real`(float4)로 뒀더니 `0.9`를 저장하고 `0.8999999761581421`을
돌려받았다. 확신도는 임계값 비교에 쓰이므로 왕복에서 값이 변하면 안 된다.
`double precision`으로 바꿨다.

### 6-3. jsonb 코덱과 이중 인코딩

asyncpg에 jsonb 코덱을 설치하면 **dict/list를 그대로** 넘겨야 한다. 미리
`json.dumps`한 문자열을 넘기면 코덱이 한 번 더 직렬화해서 JSON 문자열이 저장되고,
읽을 때 dict가 아니라 str이 돌아온다.

### 6-4. 저장소 구현 간 동작 차이

Postgres는 진행 중인 분석을 DB 제약으로 막지만 인메모리는 막지 않는다. 사용자가
보는 동작은 API 계층(`find_active`)이 같게 만들지만, **방어 깊이는 다르다.**
테스트에 이 차이를 명시해 두었다 (`test_중복_실행_방지는_DB도_강제한다`).

---

## 7. 적용

```bash
# 로컬
createdb regradar
psql -d regradar -v ON_ERROR_STOP=1 -f backend/migrations/001_initial_schema.sql

# Supabase — SQL Editor에서 001 → 002 순서로 실행
```

---

규제 변화 감지 · 직무별 대응안 생성 AI 도우미
06. 데이터 모델 / ERD · 2026-09-21
기준 문서: 03. 요구사항 정의서 / 04. 시스템 아키텍처 설계서
