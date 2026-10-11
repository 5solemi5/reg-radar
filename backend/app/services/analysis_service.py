"""법령 1건 분석 orchestration (04 설계서 §5-2, §6-1).

흐름: C3 추출 → C4 판정 → HOLD 정책(코드) → C5 영향 → C6 검증 → 결과 조립
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.ai.chains.base import ChainExecutionError, ChainRunner, ChainTrace
from app.ai.chains.c3_extract import extract_targets
from app.ai.chains.c4_mapping import (
    apply_hold_policy,
    deterministic_hold_reasons,
    map_applicability,
    unverifiable_target_reason,
)
from app.ai.chains.c5_impact import generate_impact
from app.core.config import get_settings
from app.domain.context import ContextPacket
from app.domain.enums import Applicability, ResultStatus
from app.domain.result import (
    AiInterpretation,
    AnalysisResult,
    ChangeSummary,
    DelegatedEvidence,
    LegalEvidence,
    ReferenceEvidence,
)
from app.validator.core import CHAIN_NAME as VALIDATOR_CHAIN
from app.validator.core import ValidationOutcome, validate
from app.validator.rules import normalize_for_match

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


def _split_spans(packet: ContextPacket, spans: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """검증된 인용을 모법 것과 하위법령 것으로 가른다.

    Validator는 둘 다 통과시키지만(ADR-025) 표시는 분리해야 한다. 섞어 놓으면
    사용자가 모법 조문 원문에서 찾을 수 없는 문장을 모법 인용으로 보게 된다.
    """
    parent = normalize_for_match(packet.law.original_text)
    own: list[str] = []
    by_decree: dict[str, list[str]] = {}
    for span in spans:
        needle = normalize_for_match(span)
        if needle in parent:
            own.append(span)
            continue
        for d in packet.delegated:
            if needle in normalize_for_match(d.original_text):
                by_decree.setdefault(f"{d.law_name}|{d.article_no}", []).append(span)
                break
    return own, by_decree


def _delegated_evidence(
    packet: ContextPacket, by_decree: dict[str, list[str]]
) -> list[DelegatedEvidence]:
    """근거로 실제 인용된 하위법령 조문만 남긴다.

    붙였다는 이유만으로 전부 보여주면, 판정과 무관한 조문까지 '법적 근거'로
    제시하게 된다.
    """
    return [
        DelegatedEvidence(
            law_id=d.law_id,
            law_name=d.law_name,
            law_type=d.law_type,
            article_no=d.article_no,
            article_title=d.article_title,
            source_url=d.source_url,
            quoted_spans=by_decree[f"{d.law_name}|{d.article_no}"],
            resolves_criterion=d.resolves_criterion,
        )
        for d in packet.delegated
        if f"{d.law_name}|{d.article_no}" in by_decree
    ]


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


def _rejection_feedback(outcome: ValidationOutcome) -> list[str]:
    """되먹일 거부 사유. 탈락한 인용은 문장째 보여 줘야 같은 인용을 반복하지 않는다."""
    reasons = list(outcome.report.failures)
    for span in outcome.report.dropped_spans:
        reasons.append(f"원문에서 찾을 수 없었던 인용: \"{span[:200]}\"")
    return reasons


async def _map_and_validate(
    runner: ChainRunner,
    packet: ContextPacket,
    extraction,
    feedback: list[str],
) -> ValidationOutcome:
    # C4. 사용자 매핑 판정
    applicability = await map_applicability(runner, packet, extraction, feedback or None)

    # 코드가 확정할 수 있는 HOLD 사유를 LLM 판정 위에 덮어쓴다 (AP-03, AP-04, BR-003).
    hold_reasons = deterministic_hold_reasons(packet)
    applicability = apply_hold_policy(
        applicability,
        hold_reasons,
        # 대상 집단 해당 여부를 프로필로 알 수 없으면 무관도 확정하지 않는다.
        target_reason=unverifiable_target_reason(applicability, packet),
    )

    # C5. 실무 영향 — 무관 항목에는 생성하지 않는다 (불필요한 서술 = 오탐 표면).
    impact = None
    if applicability.applicability is not Applicability.NOT_APPLICABLE:
        try:
            impact = await generate_impact(runner, packet, applicability, feedback or None)
        except ChainExecutionError:
            # 영향 생성 실패는 판정 자체를 무효화하지 않는다. 판정만 살린다 (ER-002).
            logger.warning("C5 실패 — 판정만 유지합니다: law=%s", packet.law.law_id)

    # C6. 검증 — 규칙이라 토큰은 없지만, 무엇을 왜 막았는지가 운영 지표다(R4).
    started = time.perf_counter()
    outcome = validate(packet, applicability, impact)
    runner._record(ChainTrace(
        VALIDATOR_CHAIN, "rules", int((time.perf_counter() - started) * 1000),
        ok=outcome.status is not ResultStatus.REJECTED,
        error="; ".join(outcome.report.failures) or None,
    ))
    return outcome


async def analyze_article(
    runner: ChainRunner,
    packet: ContextPacket,
    *,
    analysis_id: str | None = None,
    trace_id: str | None = None,
    max_retries: int | None = None,
) -> AnalysisOutcome:
    """조문 1건에 대한 전체 AI 판단 파이프라인."""

    # C3. 적용대상 추출
    extraction = await extract_targets(runner, packet)

    if max_retries is None:
        max_retries = get_settings().reject_retry_max

    # C4 → C5 → C6. Validator가 REJECT하면 거부 사유를 되먹여 C4부터 다시 만든다
    # (문서 11 §11-4). 결정적 게이트는 그대로다 — 재생성된 답도 같은 검증을 통과해야 한다.
    # C3(적용대상 추출)는 다시 부르지 않는다. 거부 사유는 C4·C5 서술에서 나온다.
    feedback: list[str] = []
    rejected_failures: list[str] = []
    retries = 0
    while True:
        runner.attempt = retries
        outcome = await _map_and_validate(runner, packet, extraction, feedback)
        if outcome.status is not ResultStatus.REJECTED or retries >= max_retries:
            break
        feedback = _rejection_feedback(outcome)
        rejected_failures += feedback
        retries += 1
        logger.info(
            "REJECT 재생성 %d/%d law=%s article=%s 사유=%s",
            retries, max_retries, packet.law.law_id, packet.law.article_no, feedback,
        )
    if retries:
        outcome.report = outcome.report.model_copy(
            update={"retries": retries, "rejected_failures": rejected_failures}
        )

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

    # 검증된 인용을 모법 것과 하위법령 것으로 가른다 (ADR-025).
    own_spans, decree_spans = _split_spans(packet, outcome.applicability.cited_spans)

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
        legal_evidence=_legal_evidence(packet, own_spans),
        delegated_evidence=_delegated_evidence(packet, decree_spans),
        reference_evidence=_reference_evidence(packet),
        ai_interpretation=ai,
        validation=outcome.report,
        trace_id=trace_id,
    )

    return AnalysisOutcome(
        result=result, traces=runner.traces, total_latency_ms=runner.total_latency_ms
    )
