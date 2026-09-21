"""법령 1건 분석 orchestration (04 설계서 §5-2, §6-1).

흐름: C3 추출 → C4 판정 → HOLD 정책(코드) → C5 영향 → C6 검증 → 결과 조립
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai.chains.base import ChainExecutionError, ChainRunner
from app.ai.chains.c3_extract import extract_targets
from app.ai.chains.c4_mapping import (
    apply_hold_policy,
    deterministic_hold_reasons,
    map_applicability,
)
from app.ai.chains.c5_impact import generate_impact
from app.domain.context import ContextPacket
from app.domain.enums import Applicability, ResultStatus
from app.domain.result import (
    AiInterpretation,
    AnalysisResult,
    ChangeSummary,
    LegalEvidence,
    ReferenceEvidence,
)
from app.validator.core import validate

logger = logging.getLogger(__name__)


@dataclass
class AnalysisOutcome:
    """결과 + 관측 정보 (NFR-009)."""

    result: AnalysisResult
    traces: list
    total_latency_ms: int


def _legal_evidence(packet: ContextPacket, verified_spans: list[str]) -> LegalEvidence:
    """법적 근거는 전부 LegalContext(=법제처 snapshot)에서만 채운다 (BR-001)."""
    law = packet.law
    return LegalEvidence(
        law_id=law.law_id,
        law_name=law.law_name,
        article_no=law.article_no,
        article_title=law.article_title,
        effective_date=law.effective_date,
        ministry=law.ministry,
        source_url=law.source_url,
        quoted_spans=verified_spans,
    )


def _reference_evidence(packet: ContextPacket) -> list[ReferenceEvidence]:
    return [
        ReferenceEvidence(
            doc_id=d.doc_id,
            title=d.title,
            source=d.source,
            agency=d.agency,
            published_at=d.published_at,
            doc_type=d.doc_type,
            snippet=d.snippet,
        )
        for d in packet.rag
    ]


async def analyze_article(
    runner: ChainRunner,
    packet: ContextPacket,
    *,
    analysis_id: str | None = None,
    trace_id: str | None = None,
) -> AnalysisOutcome:
    """조문 1건에 대한 전체 AI 판단 파이프라인."""

    # C3. 적용대상 추출
    extraction = await extract_targets(runner, packet)

    # C4. 사용자 매핑 판정
    applicability = await map_applicability(runner, packet, extraction)

    # 코드가 확정할 수 있는 HOLD 사유를 LLM 판정 위에 덮어쓴다 (AP-03, AP-04, BR-003).
    hold_reasons = deterministic_hold_reasons(packet, extraction)
    applicability = apply_hold_policy(applicability, hold_reasons)

    # C5. 실무 영향 — 무관 항목에는 생성하지 않는다 (불필요한 서술 = 오탐 표면).
    impact = None
    if applicability.applicability is not Applicability.NOT_APPLICABLE:
        try:
            impact = await generate_impact(runner, packet, applicability)
        except ChainExecutionError:
            # 영향 생성 실패는 판정 자체를 무효화하지 않는다. 판정만 살린다 (ER-002).
            logger.warning("C5 실패 — 판정만 유지합니다: law=%s", packet.law.law_id)

    # C6. 검증
    outcome = validate(packet, applicability, impact)

    # FR-010: 확정 판정(VALIDATED)일 때만 행동 등급을 부여한다.
    action_grade = None
    if (
        outcome.status is ResultStatus.VALIDATED
        and outcome.impact is not None
        and outcome.applicability.applicability is Applicability.APPLICABLE
    ):
        action_grade = outcome.impact.action_grade

    ai = AiInterpretation(
        reason=outcome.applicability.reason,
        matched_conditions=outcome.applicability.matched_conditions,
        missing_context=outcome.applicability.missing_context,
        impact_summary=outcome.impact.summary if outcome.impact else None,
        affected_work=outcome.impact.affected_work if outcome.impact else [],
        checklist=outcome.impact.checklist if outcome.impact else [],
        confidence=outcome.applicability.confidence,
        model=runner.llm.model_name,
    )

    result = AnalysisResult(
        analysis_id=analysis_id,
        status=outcome.status,
        applicability=outcome.applicability.applicability,
        action_grade=action_grade,
        change=ChangeSummary(
            change_type=packet.change.change_type,
            additions=packet.change.additions,
            deletions=packet.change.deletions,
            delegation_targets=packet.change.delegation_targets,
        ),
        legal_evidence=_legal_evidence(packet, outcome.applicability.cited_spans),
        reference_evidence=_reference_evidence(packet),
        ai_interpretation=ai,
        validation=outcome.report,
        trace_id=trace_id,
    )

    return AnalysisOutcome(
        result=result, traces=runner.traces, total_latency_ms=runner.total_latency_ms
    )
