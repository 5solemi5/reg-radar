# 마이그레이션

| 파일 | 대상 | 설명 |
|---|---|---|
| `001_initial_schema.sql` | 로컬 + Supabase | 테이블·인덱스·제약 |
| `002_rls_policies.sql` | **Supabase 전용** | 행 수준 보안 |
| `008_policy_workflow.sql` | 로컬 + Supabase | 사내 규정 개정 초안 승인 흐름·감사 로그 (문서 12 §4) |
| `009_trace_cost.sql` | 로컬 + Supabase | trace에 비용·프롬프트 버전·재생성 회차, Validator 행 (R4) |

`002`는 `auth.uid()`를 쓰므로 로컬 Postgres에서는 적용되지 않는다.

## 로컬 적용

```bash
createdb regradar
psql -d regradar -v ON_ERROR_STOP=1 -f migrations/001_initial_schema.sql
```

## Supabase 적용

SQL Editor에서 `001` → `002` 순서로 실행한다.

## 스키마가 강제하는 도메인 규칙

애플리케이션 코드가 뚫려도 DB가 막는 것들이다.

| 제약 | 규칙 |
|---|---|
| `action_grade_only_when_applicable` | 보류·무관에는 행동 등급을 부여하지 않는다 (BR-007, FR-010) |
| `hold_requires_missing_context` | 보류는 무엇이 부족한지 반드시 말해야 한다 (BR-003) |
| `uq_analyses_one_active_per_user` | 사용자당 진행 중인 분석은 하나만 (FR-003) |
| `analysis_results_ai_confidence_check` | confidence는 0~1 |
| `profiles` CHECK | 직무·업종에 공백만 넣을 수 없다 |
| `policy_drafts.four_eyes` | 제출자는 자기 초안을 승인·반려할 수 없다 (008) |
| `policy_drafts.decided_requires_decider` | 승인·반려 상태에는 결정자가 있어야 한다 (008) |
| `trg_policy_audit_events_append_only` | 감사 이벤트 UPDATE·DELETE 거부 — 추가 전용 (008). TRUNCATE는 막지 않는다(테스트 정리용, 운영 권한에서 회수) |

### `cardinality` vs `array_length` — 겪은 함정

`hold_requires_missing_context`를 처음에 이렇게 썼다.

```sql
CHECK (applicability <> 'HOLD' OR array_length(ai_missing_context, 1) >= 1)
```

빈 배열에 `array_length(arr, 1)`은 `0`이 아니라 **NULL**을 돌려준다. CHECK 제약은
결과가 NULL이면 **통과**시키므로, 이 제약은 정확히 막아야 할 케이스를 통과시켰다.
`cardinality()`는 빈 배열에 `0`을 돌려주므로 의도대로 동작한다.

스키마를 실제 DB에 적용해 위반 케이스를 넣어보지 않았다면 발견하지 못했을 버그다.
