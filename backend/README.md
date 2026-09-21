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
.venv/bin/python scripts/smoke_analysis.py 근로기준법 제93조  # AI Core E2E (LLM 호출)
```

`smoke_analysis.py`는 같은 조문에 세 사용자 프로필을 넣어 **무관 / 해당 / 보류**로
갈리는지 확인합니다 (기획서 §13 '입력 비교' 장면).

## 디렉터리 구조

| 경로 | 책임 | 관련 원칙 |
|---|---|---|
| `app/core/` | 설정. secret은 환경변수로만 | NFR-008 |
| `app/domain/context.py` | LLM **입력** Context (User/Legal/Change/Rag) | AP-06 |
| `app/domain/outputs.py` | LLM **출력** 스키마. 공식 사실 필드 자체가 없음 | FR-020 |
| `app/domain/result.py` | 최종 결과. 법적근거/참고자료/AI해석 필드 분리 | AP-05, FR-014 |
| `app/adapters/law/` | 법제처 OPEN API — 공식 사실값의 유일한 공급원 | AP-01, BR-001 |
| `app/diff/engine.py` | 신구법 diff + 하위법령 위임 감지. 전부 코드 | BR-002, Q5 |
| `app/diff/headcount.py` | 상시근로자 수 기준 충족 판정. 산술은 코드가 | AP-03 |
| `app/ai/llm.py` | LLM provider 추상화 | NFR-012 |
| `app/ai/context_builder.py` | 입력 packet 렌더링 | AP-06 |
| `app/ai/chains/` | C3 추출 → C4 매핑 → C5 영향 | AP-02 |
| `app/validator/` | C6. 인용·금지필드·HOLD 검증 | FR-020~022 |
| `app/services/analysis_service.py` | C3~C6 orchestration + 결과 조립 | 04 §5-2 |
| `evaluation/` | 평가 데이터셋·지표·리포트 ([README](evaluation/README.md)) | 기획서 §11 |

## 설계상 지켜지는 불변식

1. **법령 사실값은 LLM이 만들 수 없다.** `ApplicabilityOutput` / `ImpactOutput` 스키마에
   `law_name`, `article_no`, `effective_date` 같은 필드가 아예 존재하지 않는다.
   `assert_no_forbidden_fields()`가 이를 테스트에서 강제한다.
2. **변화는 코드가 감지한다.** `compute_change()`의 출력에 없는 변경점은 모델도 말할 수 없다.
3. **불확실하면 HOLD.** `ApplicabilityOutput`은 HOLD인데 `missing_context`가 비면
   스키마 단계에서 거부된다.
4. **근거는 섞이지 않는다.** `LegalEvidence` / `ReferenceEvidence` / `AiInterpretation`이
   별도 타입이라 데이터 모델 수준에서 혼합이 불가능하다.
5. **산술은 LLM에 맡기지 않는다.** "상시 10명 이상" 같은 규모 기준 충족 여부는
   `app/diff/headcount.py`가 계산해 사실로 주입한다. 첫 E2E에서 LLM이 이 판단을
   '용어 정의가 불명확하다'며 회피해 세 프로필이 전부 보류로 나온 회귀가 있었다.
6. **근거 없는 '해당'은 차단된다.** 검증된 인용이 하나도 남지 않은 APPLICABLE은
   Validator가 REJECT한다 — 이 서비스에서 가장 위험한 출력이기 때문이다 (Q2).

## 평가 실측 (2026-09-21 · 15케이스)

| 지표 | 목표 | gpt-4o | gpt-4o-mini |
|---|---|---|---|
| 판정 정확도 | — | **100%** | 86.7% |
| Q2 오탐률 | ≤ 5% | 0% | 0% |
| Q4 재현율 | ≥ 90% | 100% | 60% ✗ |
| Q6 금지 필드 유출 | 0건 | 0건 | 0건 |

기본 모델이 `gpt-4o`인 이유는 gpt-4o-mini가 Q4 재현율 60%로 NFR-003을 충족하지
못했기 때문이다. 수치를 읽는 법과 과적합 주의사항은 `evaluation/README.md` 참조.
