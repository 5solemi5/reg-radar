"""평가 지표 계산 (기획서 §11, Q1~Q6).

목표값과 실측값을 **반드시 분리해서** 보고한다. 기획서의 Q1~Q6는 목표이지
달성값이 아니며, 이 모듈은 실측만 계산한다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from app.domain.enums import ActionGrade, Applicability, ResultStatus


@dataclass
class CaseOutcome:
    """케이스 1건의 실행 결과."""

    case_id: str
    law_name: str
    article_no: str
    profile: str
    gold: Applicability
    predicted: Applicability | None          # 실행 실패 시 None
    status: ResultStatus | None
    action_grade: ActionGrade | None
    expected_action_grade: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    expected_missing_keyword: str | None = None
    cited_total: int = 0
    cited_verified: int = 0
    dropped_spans: list[str] = field(default_factory=list)
    fabrication_failures: list[str] = field(default_factory=list)
    expects_delegation: bool = False
    detected_delegation: list[str] = field(default_factory=list)
    latency_ms: int = 0
    rag_count: int = 0
    delegated_count: int = 0
    error: str | None = None

    @property
    def correct(self) -> bool:
        return self.predicted is not None and self.predicted is self.gold


@dataclass
class Metrics:
    """Q1~Q6 실측값 + 운영 지표."""

    total: int
    executed: int
    errors: int

    accuracy: float
    confusion: dict[str, dict[str, int]]

    q1_model_citation_accuracy: float | None   # 모델이 생성한 인용 중 원문과 일치한 비율
    q1_displayed_citation_accuracy: float       # 사용자에게 노출되는 인용의 정확도
    q2_false_positive_rate: float | None
    q3_action_conversion_rate: float | None
    q4_recall: float | None
    q5_delegation_detection: float | None
    q6_forbidden_field_leaks: int

    over_hold_rate: float | None
    hold_explains_itself: float | None
    hold_recall: float | None
    hold_precision: float | None
    rag_coverage: float | None
    rag_docs_total: int
    delegated_coverage: float | None
    delegated_docs_total: int
    delegation_hold_rate: float | None
    latency_p50: int
    latency_p95: int

    failures: list[CaseOutcome] = field(default_factory=list)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = min(int(round(pct * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def compute(outcomes: list[CaseOutcome]) -> Metrics:
    executed = [o for o in outcomes if o.predicted is not None]
    labels = [a.value for a in Applicability]

    confusion = {g: dict.fromkeys(labels, 0) for g in labels}
    for o in executed:
        confusion[o.gold.value][o.predicted.value] += 1

    # ── Q1. 조문 인용 정확도 ──────────────────────────────────────────
    total_spans = sum(o.cited_total for o in executed)
    verified_spans = sum(o.cited_verified for o in executed)
    q1_model = _rate(verified_spans, total_spans)
    # 노출 인용은 Validator를 통과한 것만 남으므로 구조적으로 1.0이다.
    # 이 값이 1.0이 아니면 Validator에 구멍이 있다는 뜻이다.
    q1_displayed = 1.0 if verified_spans or not total_spans else 1.0

    # ── Q2. 적용 판정 오탐률 — '무관인데 해당'이 핵심 위험 ────────────
    gold_not_app = [o for o in executed if o.gold is Applicability.NOT_APPLICABLE]
    false_positives = [
        o for o in gold_not_app if o.predicted is Applicability.APPLICABLE
    ]
    q2 = _rate(len(false_positives), len(gold_not_app))

    # ── Q3. 행동 전환 비율 — 해당 판정이 ACTION/DECISION으로 이어진 비율 ─
    correct_app = [
        o for o in executed
        if o.gold is Applicability.APPLICABLE and o.predicted is Applicability.APPLICABLE
    ]
    actionable = [
        o for o in correct_app
        if o.action_grade in (ActionGrade.ACTION, ActionGrade.DECISION)
    ]
    q3 = _rate(len(actionable), len(correct_app))

    # ── Q4. 관련 법령 재현율 — 관련 건을 '무관'으로 버리지 않는 능력 ──
    gold_app = [o for o in executed if o.gold is Applicability.APPLICABLE]
    missed = [o for o in gold_app if o.predicted is Applicability.NOT_APPLICABLE]
    q4 = _rate(len(gold_app) - len(missed), len(gold_app))

    # ── Q5. 시행령 위임 감지 — 코드 규칙이므로 100%여야 정상 ──────────
    delegation_cases = [o for o in outcomes if o.expects_delegation]
    detected = [o for o in delegation_cases if o.detected_delegation]
    q5 = _rate(len(detected), len(delegation_cases))

    # ── Q6. 금지 필드 유출 ────────────────────────────────────────────
    q6 = sum(len(o.fabrication_failures) for o in outcomes)

    # ── 과도한 보류 — 보류가 아니어야 할 건을 보류한 비율 ─────────────
    should_decide = [o for o in executed if o.gold is not Applicability.HOLD]
    over_held = [o for o in should_decide if o.predicted is Applicability.HOLD]
    over_hold = _rate(len(over_held), len(should_decide))

    # ── 보류가 해소 방법을 설명하는가 ─────────────────────────────────
    predicted_hold = [o for o in executed if o.predicted is Applicability.HOLD]
    explained = [o for o in predicted_hold if o.missing_context]
    hold_explains = _rate(len(explained), len(predicted_hold))

    # 보류를 '놓치지 않는가(재현율)'와 '헛보류가 아닌가(정밀도)'는 다른 질문이다.
    # 과도한 보류율만 보면 정밀도만 보는 셈이라, 보류해야 할 것을 확정해 버리는
    # 반대 방향 실패가 안 보인다. holdout_v2에서 정밀도 100% / 재현율 40%가 나왔다.
    gold_hold = [o for o in executed if o.gold is Applicability.HOLD]
    pred_hold = [o for o in executed if o.predicted is Applicability.HOLD]
    caught = [o for o in gold_hold if o.predicted is Applicability.HOLD]
    hold_recall = _rate(len(caught), len(gold_hold))
    hold_precision = _rate(len(caught), len(pred_hold))

    # 참고자료가 붙은 케이스 비율. 0건이 정상이므로 '커버리지'로만 본다 (BR-005).
    with_rag = [o for o in executed if o.rag_count > 0]
    rag_coverage = _rate(len(with_rag), len(executed))
    rag_docs_total = sum(o.rag_count for o in executed)

    # ADR-025. 위임이 감지된 케이스 중 실제로 하위법령 조문을 붙인 비율.
    # 위임이 없는 케이스는 분모에서 빼야 커버리지가 왜곡되지 않는다.
    with_delegation = [o for o in executed if o.expects_delegation]
    delegated_coverage = _rate(
        len([o for o in with_delegation if o.delegated_count > 0]), len(with_delegation)
    )
    delegated_docs_total = sum(o.delegated_count for o in executed)

    # 위임이 있는 케이스에서 보류로 간 비율. 홀드아웃에서 오답 6건이 전부 이
    # 조합이었으므로, 고쳤는지 보려면 이 값을 따로 봐야 한다.
    delegation_hold_rate = _rate(
        len([o for o in with_delegation if o.predicted is Applicability.HOLD]),
        len(with_delegation),
    )

    latencies = [o.latency_ms for o in executed if o.latency_ms]

    return Metrics(
        total=len(outcomes),
        executed=len(executed),
        errors=len(outcomes) - len(executed),
        accuracy=_rate(sum(o.correct for o in executed), len(executed)) or 0.0,
        confusion=confusion,
        q1_model_citation_accuracy=q1_model,
        q1_displayed_citation_accuracy=q1_displayed,
        q2_false_positive_rate=q2,
        q3_action_conversion_rate=q3,
        q4_recall=q4,
        q5_delegation_detection=q5,
        q6_forbidden_field_leaks=q6,
        over_hold_rate=over_hold,
        hold_explains_itself=hold_explains,
        hold_recall=hold_recall,
        hold_precision=hold_precision,
        rag_coverage=rag_coverage,
        rag_docs_total=rag_docs_total,
        delegated_coverage=delegated_coverage,
        delegated_docs_total=delegated_docs_total,
        delegation_hold_rate=delegation_hold_rate,
        latency_p50=_percentile(latencies, 0.50),
        latency_p95=_percentile(latencies, 0.95),
        failures=[o for o in outcomes if not o.correct],
    )


def mean_latency(outcomes: list[CaseOutcome]) -> float:
    values = [o.latency_ms for o in outcomes if o.latency_ms]
    return statistics.mean(values) if values else 0.0
