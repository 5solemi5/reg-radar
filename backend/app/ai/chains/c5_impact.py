"""C5. 실무 영향 + 행동 등급 (FR-009, FR-010)."""

from __future__ import annotations

from app.ai.chains.base import ChainRunner
from app.ai.context_builder import build_blocks
from app.ai.prompts import C5_IMPACT
from app.domain.context import ContextPacket
from app.domain.outputs import ApplicabilityOutput, ImpactOutput

CHAIN_NAME = "C5_practical_impact"


async def generate_impact(
    runner: ChainRunner,
    packet: ContextPacket,
    applicability: ApplicabilityOutput,
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
    return await runner.invoke(chain=CHAIN_NAME, prompt=prompt, schema=ImpactOutput)
