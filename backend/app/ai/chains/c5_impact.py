"""C5. 실무 영향 + 행동 등급 (FR-009, FR-010)."""

from __future__ import annotations

from app.ai.chains.base import ChainRunner
from app.ai.chains.c4_mapping import render_rejection_feedback
from app.ai.context_builder import build_blocks
from app.ai.prompts import C5_IMPACT
from app.domain.context import ContextPacket
from app.domain.outputs import ApplicabilityOutput, ImpactOutput

CHAIN_NAME = "C5_practical_impact"


async def generate_impact(
    runner: ChainRunner,
    packet: ContextPacket,
    applicability: ApplicabilityOutput,
    feedback: list[str] | None = None,
) -> ImpactOutput:
    blocks = build_blocks(packet)
    prompt = C5_IMPACT.format(
        user_block=blocks["user_block"],
        law_block=blocks["law_block"],
        change_block=blocks["change_block"],
        rag_block=blocks["rag_block"],
        applicability=applicability.applicability.value,
        reason=applicability.reason,
    )
    if feedback:  # REJECT 재생성 — 없으면 프롬프트가 그대로다 (c4_mapping 참조)
        prompt += render_rejection_feedback(feedback)
    return await runner.invoke(chain=CHAIN_NAME, prompt=prompt, schema=ImpactOutput)
