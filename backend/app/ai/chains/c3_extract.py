"""C3. 적용대상 구조화 추출 (FR-006)."""

from __future__ import annotations

from app.ai.chains.base import ChainRunner
from app.ai.context_builder import build_blocks
from app.ai.prompts import C3_EXTRACT
from app.domain.context import ContextPacket
from app.domain.outputs import TargetExtractionOutput

CHAIN_NAME = "C3_target_extraction"


async def extract_targets(runner: ChainRunner, packet: ContextPacket) -> TargetExtractionOutput:
    blocks = build_blocks(packet)
    prompt = C3_EXTRACT.format(
        law_block=blocks["law_block"], change_block=blocks["change_block"]
    )
    return await runner.invoke(
        chain=CHAIN_NAME, prompt=prompt, schema=TargetExtractionOutput
    )
