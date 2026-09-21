"""C4. 사용자 ↔ 법령 매핑 판정 (FR-007).

BR-003을 프롬프트에만 맡기지 않는다. 하위법령 위임이 있거나 규모 조건이 있는데
사용자 규모 정보가 없으면, LLM 판정과 무관하게 **코드가 HOLD로 강등**한다.
"""

from __future__ import annotations

from app.ai.chains.base import ChainRunner
from app.ai.context_builder import build_blocks, render_conditions_block
from app.ai.prompts import C4_MAPPING
from app.diff.headcount import SizeVerdict
from app.diff.headcount import evaluate as evaluate_headcount
from app.domain.context import ContextPacket
from app.domain.enums import Applicability
from app.domain.outputs import ApplicabilityOutput, TargetExtractionOutput

CHAIN_NAME = "C4_applicability_mapping"


async def map_applicability(
    runner: ChainRunner,
    packet: ContextPacket,
    extraction: TargetExtractionOutput,
) -> ApplicabilityOutput:
    blocks = build_blocks(packet)
    prompt = C4_MAPPING.format(
        user_block=blocks["user_block"],
        law_block=blocks["law_block"],
        change_block=blocks["change_block"],
        rag_block=blocks["rag_block"],
        size_block=blocks["size_block"],
        conditions_block=render_conditions_block(extraction),
    )
    return await runner.invoke(chain=CHAIN_NAME, prompt=prompt, schema=ApplicabilityOutput)


def deterministic_hold_reasons(packet: ContextPacket) -> list[str]:
    """코드로 확정할 수 있는 HOLD 사유를 모은다 (AP-03, AP-04, BR-003).

    LLM이 'APPLICABLE'이라고 말해도 이 목록이 비어 있지 않으면 확정하지 않는다.
    이것이 기획서 §2의 '규모 조건을 놓친 20% 오탐'을 막는 주된 장치다.
    """
    reasons: list[str] = []

    # 1) 하위법령 위임: 구체 기준이 조문 밖에 있다 (Q5).
    if packet.change.has_delegation:
        targets = ", ".join(packet.change.delegation_targets)
        reasons.append(f"구체적 기준이 {targets}에 위임되어 조문만으로 확정할 수 없습니다.")

    # 2) 규모 기준이 조문에 있는데 사용자 상시근로자 수가 미상.
    #    조건 존재 여부를 LLM의 kind 라벨이 아니라 원문 정규식으로 판정한다.
    #    LLM이 규모 조건을 'other'로 분류해도 보류가 누락되지 않게 하기 위함이다.
    size = evaluate_headcount(packet.law.original_text, packet.user.employee_count)
    if size.verdict is SizeVerdict.UNKNOWN:
        found = ", ".join(t.raw for t in size.thresholds)
        reasons.append(
            f"조문에 규모 기준({found})이 있으나 상시근로자 수가 입력되지 않아 "
            "충족 여부를 확인할 수 없습니다."
        )
    # 원문에 규모 기준이 없으면 C3가 'size' 조건을 만들어냈더라도 보류하지 않는다.
    # 폴백으로 C3 라벨을 신뢰했더니, 규모 조건이 없는 조문(근로기준법 제54조 휴게)에서
    # '상시근로자 수 미상'을 이유로 보류하는 오답이 실측에서 나왔다.

    return reasons


def apply_hold_policy(
    output: ApplicabilityOutput, hold_reasons: list[str]
) -> ApplicabilityOutput:
    """HOLD 사유가 있으면 APPLICABLE을 HOLD로 강등한다.

    NOT_APPLICABLE은 강등하지 않는다. '적용되지 않는다'는 판단은 추가정보가 없어도
    성립할 수 있고, 무관 항목까지 HOLD로 만들면 대시보드가 보류로 가득 차기 때문이다.
    """
    if not hold_reasons or output.applicability is not Applicability.APPLICABLE:
        return output

    merged = list(dict.fromkeys([*output.missing_context, *hold_reasons]))
    return output.model_copy(
        update={
            "applicability": Applicability.HOLD,
            "missing_context": merged,
            "reason": f"{output.reason}\n\n[보류 사유] " + " ".join(hold_reasons),
        }
    )
