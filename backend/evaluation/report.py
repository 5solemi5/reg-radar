"""평가 결과 리포트.

기획서 §11의 목표값과 이번 실행의 실측값을 **나란히, 그러나 구분해서** 출력한다.
목표 달성 여부를 판정하되 목표값을 실측인 것처럼 섞어 쓰지 않는다.
"""

from __future__ import annotations

from app.domain.enums import Applicability
from evaluation.metrics import CaseOutcome, Metrics


# (지표명, 목표 설명, 목표 충족 판정 함수)
def _at_least(bound: float):
    return lambda v: v is not None and v >= bound


def _at_most(bound: float):
    return lambda v: v is not None and v <= bound


TARGETS = {
    "q1_displayed_citation_accuracy": ("Q1 노출 인용 정확도", "100%", _at_least(1.0)),
    "q1_model_citation_accuracy": ("  └ 모델 생성 인용 정확도", "(참고)", lambda v: None),
    "q2_false_positive_rate": ("Q2 적용 판정 오탐률", "≤ 5%", _at_most(0.05)),
    "q3_action_conversion_rate": ("Q3 행동 전환 비율", "≥ 60%", _at_least(0.60)),
    "q4_recall": ("Q4 관련 법령 재현율", "≥ 90%", _at_least(0.90)),
    "q5_delegation_detection": ("Q5 시행령 위임 감지", "100%", _at_least(1.0)),
}


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def render(metrics: Metrics, outcomes: list[CaseOutcome], model: str) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 74)
    add(f"평가 결과 · 모델 {model}")
    add("=" * 74)
    add(f"케이스 {metrics.total}건 (실행 {metrics.executed} / 실패 {metrics.errors})")
    add(f"판정 정확도 {_pct(metrics.accuracy)}")
    add("")

    add("── Q1~Q6 실측 ───────────────────────────────────────────────────────")
    add(f"{'지표':<26}{'목표':>10}{'실측':>12}  판정")
    for key, (name, target, passes) in TARGETS.items():
        value = getattr(metrics, key)
        outcome = passes(value)
        if value is None:
            verdict = "—"
        elif outcome is None:
            verdict = "참고"
        else:
            verdict = "달성" if outcome else "미달"
        add(f"{name:<26}{target:>10}{_pct(value):>12}  {verdict}")
    leaks = metrics.q6_forbidden_field_leaks
    q6_ok = "달성" if leaks == 0 else "미달"
    add(f"{'Q6 금지 필드 유출':<26}{'0건':>10}{f'{leaks}건':>12}  {q6_ok}")
    add("")

    add("── 보류 품질 (기획서 목표에는 없으나 제품 가치에 직결) ──────────────")
    add(f"{'과도한 보류율':<26}{'낮을수록 좋음':>10}{_pct(metrics.over_hold_rate):>12}")
    add(f"{'보류가 해소방법 제시':<26}{'100%':>10}{_pct(metrics.hold_explains_itself):>12}")
    add("")

    recall = _pct(metrics.hold_recall)
    precision = _pct(metrics.hold_precision)
    add(f"{'보류 재현율 (놓치지 않는가)':<26}{'높을수록 좋음':>10}{recall:>12}")
    add(f"{'보류 정밀도 (헛보류 아닌가)':<26}{'높을수록 좋음':>10}{precision:>12}")
    add("")
    add("── 위임 하위법령 (ADR-025) ──────────────────────────────────────────")
    add(f"{'위임 케이스 중 조문 확보':<26}{'':>10}{_pct(metrics.delegated_coverage):>12}")
    add(f"{'위임 조문 총 건수':<26}{'':>10}{str(metrics.delegated_docs_total) + '건':>12}")
    hold_rate = _pct(metrics.delegation_hold_rate)
    add(f"{'위임 케이스의 보류율':<26}{'낮을수록 좋음':>10}{hold_rate:>12}")
    add("")
    add("── 참고자료 (RAG) ───────────────────────────────────────────────────")
    add(f"{'참고자료가 붙은 케이스':<26}{'':>10}{_pct(metrics.rag_coverage):>12}")
    add(f"{'참고자료 총 건수':<26}{'':>10}{str(metrics.rag_docs_total) + '건':>12}")
    add("")

    add("── 응답 성능 (NFR-006) ──────────────────────────────────────────────")
    add(f"조문 1건당 latency  p50 {metrics.latency_p50}ms · p95 {metrics.latency_p95}ms")
    add("")

    add("── 혼동 행렬 (행=정답, 열=예측) ─────────────────────────────────────")
    labels = [a.value for a in Applicability]
    header = " " * 18 + "".join(f"{lab:>17}" for lab in labels)
    add(header)
    for gold in labels:
        row = "".join(f"{metrics.confusion[gold][p]:>17}" for p in labels)
        add(f"{gold:<18}{row}")
    add("")

    wrong = [o for o in outcomes if o.predicted is not None and not o.correct]
    if wrong:
        add("── 오답 분석 ────────────────────────────────────────────────────────")
        for o in wrong:
            add(f"  {o.case_id} {o.law_name} {o.article_no} [{o.profile}]")
            add(f"     정답 {o.gold.value} → 예측 {o.predicted.value} (status={o.status.value})")
            if o.missing_context:
                add(f"     보류 사유: {o.missing_context}")
        add("")

    errored = [o for o in outcomes if o.error]
    if errored:
        add("── 실행 실패 ────────────────────────────────────────────────────────")
        for o in errored:
            add(f"  {o.case_id}: {o.error}")
        add("")

    dropped = [o for o in outcomes if o.dropped_spans]
    if dropped:
        add("── 검증 탈락 인용 (Validator가 제거) ────────────────────────────────")
        for o in dropped:
            add(f"  {o.case_id}: {o.dropped_spans}")
        add("")

    add("※ Q1: '노출 인용'은 Validator 통과분으로 구조적으로 100%다. 모델이 만든 인용")
    add("   자체의 정확도는 그 아래 참고값이며, 둘의 차이가 Validator가 막아낸 양이다.")
    add("※ 목표값은 기획서 §11의 설계 목표이며 달성 보증이 아니다.")
    add("※ 실측값은 이 데이터셋·이 모델 기준이며 표본이 작다. 케이스 확대 시 재측정 필요.")
    return "\n".join(lines)
