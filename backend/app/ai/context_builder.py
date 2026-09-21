"""Context Builder — LLM 입력 packet을 문자열 블록으로 렌더링한다.

04 설계서 §4: Context Builder는 공식 fact를 **수정하지 않는다**. 조합만 한다.
RAG 블록은 항상 '참고자료'로 라벨링되어 법적 근거와 섞이지 않는다 (AP-05).
"""

from __future__ import annotations

from app.ai.prompts import NO_DELEGATED_PLACEHOLDER, NO_RAG_PLACEHOLDER
from app.diff.headcount import evaluate as evaluate_headcount
from app.domain.context import ContextPacket, DelegatedContext, RagContext
from app.domain.outputs import TargetExtractionOutput


def render_rag_block(docs: list[RagContext]) -> str:
    """BR-005: 검색 결과 0건은 정상이며, 모델이 빈자리를 채우지 못하게 명시한다."""
    if not docs:
        return NO_RAG_PLACEHOLDER
    return "\n\n".join(doc.to_prompt_block(i + 1) for i, doc in enumerate(docs))


def render_delegated_block(docs: list[DelegatedContext]) -> str:
    """ADR-025. 모법이 위임한 하위법령 조문을 붙인다.

    비어 있는 경우와 있는 경우의 의미가 정반대다. 비어 있으면 위임된 기준을
    확인할 방법이 없다는 뜻이므로 보류가 맞고, 있으면 기준이 눈앞에 있으니
    보류할 이유가 없다. 그 차이를 모델이 오해하지 않도록 문구로 못 박는다.
    """
    if not docs:
        return NO_DELEGATED_PLACEHOLDER
    return "\n\n".join(doc.to_prompt_block() for doc in docs)


def render_conditions_block(extraction: TargetExtractionOutput) -> str:
    if not extraction.conditions and not extraction.missing_context:
        return "(추출된 적용조건이 없습니다.)"

    lines: list[str] = []
    for i, cond in enumerate(extraction.conditions, start=1):
        required = "필수" if cond.is_required else "단서/예외"
        lines.append(f"{i}. [{cond.kind}/{required}] {cond.description}")
        lines.append(f'   근거 인용: "{cond.cited_span}"')
    if extraction.exceptions:
        lines.append("\n적용 제외/단서:")
        lines.extend(f"  - {e}" for e in extraction.exceptions)
    if extraction.missing_context:
        lines.append("\n조문만으로 확정 불가한 요소:")
        lines.extend(f"  - {m}" for m in extraction.missing_context)
    return "\n".join(lines)


def build_blocks(packet: ContextPacket) -> dict[str, str]:
    """프롬프트 템플릿에 채울 블록들. 모든 값은 deterministic layer 산출물이다."""
    return {
        "user_block": packet.user.to_prompt_block(),
        "law_block": packet.law.to_prompt_block(),
        "change_block": packet.change.to_prompt_block(),
        "rag_block": render_rag_block(packet.rag),
        # ADR-025: 위임 문구만 보고 보류하지 않도록 위임된 실제 기준을 함께 준다.
        "delegated_block": render_delegated_block(packet.delegated),
        # AP-03: 규모 기준 충족 여부는 산술이므로 코드가 계산해 사실로 주입한다.
        "size_block": evaluate_headcount(
            packet.law.original_text, packet.user.employee_count
        ).to_prompt_block(),
    }
