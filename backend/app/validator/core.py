"""C6 Validator — AI 출력의 최종 관문 (FR-020, FR-021, FR-022, ER-004).

정책:
  · 인용이 원문에 없으면 그 인용을 **제거**한다.
  · 근거가 하나도 남지 않은 APPLICABLE은 **REJECT** 한다.
    "해당한다"는 확정은 이 서비스에서 가장 위험한 출력이고(Q2 오탐),
    검증 가능한 근거 없이 내보낼 이유가 없다.
  · 조문번호·날짜·참고출처를 지어낸 흔적이 있으면 **REJECT** 한다 (Q6 금지 필드 유출 0건).
  · HOLD 결과에는 행동 등급을 확정하지 않는다 (FR-010).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.context import ContextPacket
from app.domain.enums import Applicability, ResultStatus
from app.domain.outputs import ApplicabilityOutput, ImpactOutput
from app.domain.result import ValidationReport
from app.validator.rules import (
    find_fabricated_article_refs,
    find_fabricated_dates,
    find_phantom_rag_refs,
    verify_citations,
)

CHAIN_NAME = "C6_validator"


@dataclass
class ValidationOutcome:
    """검증 결과 + 정제된 출력."""

    report: ValidationReport
    applicability: ApplicabilityOutput
    impact: ImpactOutput | None
    status: ResultStatus

    @property
    def accepted(self) -> bool:
        return self.status is not ResultStatus.REJECTED


def _ai_narrative(
    applicability: ApplicabilityOutput, impact: ImpactOutput | None
) -> str:
    """위조 탐지 대상이 되는 AI 자유 서술 전체를 모은다."""
    parts: list[str] = [applicability.reason, *applicability.matched_conditions,
                        *applicability.missing_context]
    if impact is not None:
        parts += [impact.summary, impact.action_grade_reason, *impact.affected_work]
        parts += [item.title for item in impact.checklist]
        parts += [item.detail for item in impact.checklist if item.detail]
    return "\n".join(parts)


def validate(
    packet: ContextPacket,
    applicability: ApplicabilityOutput,
    impact: ImpactOutput | None = None,
) -> ValidationOutcome:
    checks: dict[str, bool] = {}
    failures: list[str] = []

    original = packet.law.original_text

    # ── 1. 인용 검증 (FR-021) ──────────────────────────────────────────
    app_spans, app_dropped = verify_citations(applicability.cited_spans, original)
    impact_spans, impact_dropped = (
        verify_citations(impact.cited_spans, original) if impact else ([], [])
    )
    dropped = [*app_dropped, *impact_dropped]
    checks["citation"] = not dropped
    if dropped:
        failures.append(f"원문에서 확인되지 않은 인용 {len(dropped)}건을 제거했습니다.")

    applicability = applicability.model_copy(update={"cited_spans": app_spans})
    if impact is not None:
        impact = impact.model_copy(update={"cited_spans": impact_spans})

    # ── 2. 금지 필드 위조 탐지 (FR-020, Q6) ────────────────────────────
    narrative = _ai_narrative(applicability, impact)

    fake_articles = find_fabricated_article_refs(narrative, packet)
    checks["no_fabricated_article_no"] = not fake_articles
    if fake_articles:
        failures.append(f"근거 범위 밖 조문번호를 생성했습니다: {', '.join(fake_articles)}")

    fake_dates = find_fabricated_dates(narrative, packet)
    checks["no_fabricated_date"] = not fake_dates
    if fake_dates:
        failures.append(f"근거 범위 밖 날짜를 생성했습니다: {', '.join(fake_dates)}")

    phantom_rag = find_phantom_rag_refs(narrative, packet)
    checks["no_phantom_reference"] = not phantom_rag
    if phantom_rag:
        failures.append(f"존재하지 않는 참고자료를 인용했습니다: {', '.join(phantom_rag)}")

    # ── 3. HOLD 규칙 (BR-003) ──────────────────────────────────────────
    hold_ok = (
        applicability.applicability is not Applicability.HOLD
        or bool(applicability.missing_context)
    )
    checks["hold_has_missing_context"] = hold_ok
    if not hold_ok:
        failures.append("HOLD 판정에 missing_context가 없습니다.")

    # ── 4. 근거 있는 확정만 허용 (Q2 오탐 방지) ────────────────────────
    substantiated = (
        applicability.applicability is not Applicability.APPLICABLE or bool(app_spans)
    )
    checks["applicable_has_citation"] = substantiated
    if not substantiated:
        failures.append("검증된 원문 인용 없이 '해당'으로 확정할 수 없습니다.")

    # ── 판정 ───────────────────────────────────────────────────────────
    fatal = not (
        checks["no_fabricated_article_no"]
        and checks["no_fabricated_date"]
        and checks["no_phantom_reference"]
        and checks["hold_has_missing_context"]
        and checks["applicable_has_citation"]
    )

    if fatal:
        status = ResultStatus.REJECTED
    elif applicability.applicability is Applicability.HOLD:
        status = ResultStatus.HOLD
    else:
        status = ResultStatus.VALIDATED

    # FR-010(보류에 행동 등급을 확정하지 않는 것)은 결과 조립 단계에서 처리한다.
    # ImpactOutput.action_grade는 필수 필드이고, 등급을 비울 수 있는 곳은
    # AnalysisResult.action_grade(Optional)뿐이기 때문이다.

    report = ValidationReport(
        passed=not fatal and not dropped,
        checks=checks,
        failures=failures,
        dropped_spans=dropped,
        downgraded_to_hold=status is ResultStatus.HOLD,
    )
    return ValidationOutcome(
        report=report, applicability=applicability, impact=impact, status=status
    )
