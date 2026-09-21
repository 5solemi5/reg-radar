"""C4. 사용자 ↔ 법령 매핑 판정 (FR-007).

BR-003을 프롬프트에만 맡기지 않는다. 확정에 필요한 사실이 없으면 LLM 판정과
무관하게 **코드가 HOLD로 강등**한다.

강등 조건은 '정보가 없는가'이지 '위임이 있는가'가 아니다. 둘을 같게 보면 위임
문구가 있다는 이유만으로 명백히 적용되는 조문까지 보류로 간다 (ADR-025).
"""

from __future__ import annotations

from app.ai.chains.base import ChainRunner
from app.ai.context_builder import build_blocks, render_conditions_block
from app.ai.prompts import C4_MAPPING
from app.diff.headcount import SizeVerdict
from app.diff.headcount import evaluate as evaluate_headcount
from app.domain.context import ContextPacket
from app.domain.enums import Applicability
from app.domain.outputs import (
    ApplicabilityOutput,
    TargetExtractionOutput,
    TargetGroupBasis,
)
from app.validator.rules import normalize_for_match

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
        delegated_block=blocks["delegated_block"],
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
    #
    #    단, 그 하위법령 조문을 확보했으면 기준은 더 이상 조문 밖에 있지 않다 (ADR-025).
    #    홀드아웃 평가에서 오답 6건이 전부 이 규칙 때문이었다. 위임이 적용 여부를
    #    가르는지 세부 절차에 관한 것인지 구분하지 않고 무조건 강등했더니, 최저임금법
    #    제6조(최저임금 지급 의무)처럼 명백히 적용되는 조문까지 "확정할 수 없다"가 됐다.
    #    위임된 기준을 프롬프트에 넣어준 뒤에는 그 구분을 LLM이 할 수 있다.
    #
    #    단 '조문을 찾았다'가 아니라 '기준을 손에 넣었다'여야 한다. 시행령이 다시
    #    별표로 넘기면 기준은 여전히 없으므로 보류를 유지한다 (criterion_resolved).
    if packet.change.has_delegation and not packet.criterion_resolved:
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


def unverifiable_target_reason(
    output: ApplicabilityOutput, packet: ContextPacket | None = None
) -> str | None:
    """대상 집단 해당 여부를 프로필로 판단할 수 없으면 그 사유를 만든다 (AP-03).

    규모 기준은 코드가 계산해 강제하는데, '이 회사가 도급인인가'처럼 지위에 관한
    미지수는 LLM에 맡겨져 있었다. 그리고 프롬프트가 "보류를 남용하지 마십시오"로
    강하게 눌러 놓아서, 모르는 것도 업종만 보고 결정했다. holdout_v2에서 보류
    재현율 40%로 나타났고 놓친 3건이 전부 이 유형이었다.

    판단은 LLM이 하되(의미 해석) 그 결과를 강제하는 것은 코드다. 모델에게 묻는
    질문이 '적용되는가'가 아니라 '판단할 정보가 있는가'로 바뀐 것이 핵심이다.
    """
    target = output.target_group.strip() or "이 조문의 대상"
    unknown = f"귀사가 '{target}'에 해당하는지가 프로필에 없어 확인할 수 없습니다."

    if output.target_group_basis is TargetGroupBasis.PROFILE_SILENT:
        return unknown

    # 확정했다면 프로필의 어느 줄을 보고 그랬는지 대조한다 (FR-021과 같은 방식).
    # 스키마가 값을 요구하지만 그 값이 **실제 프로필에 있는지**는 코드가 본다.
    # 요구만 했을 때 모델은 그럴듯한 문장을 지어냈다.
    if packet is None:
        return None
    evidence = normalize_for_match(output.profile_evidence or "")
    if evidence and evidence in normalize_for_match(packet.user.to_prompt_block()):
        return None
    return unknown


def apply_hold_policy(
    output: ApplicabilityOutput,
    hold_reasons: list[str],
    *,
    target_reason: str | None = None,
) -> ApplicabilityOutput:
    """HOLD 사유가 있으면 판정을 HOLD로 강등한다.

    강등 범위가 사유에 따라 다르다.

    - `hold_reasons`(위임·규모 미상)는 **APPLICABLE만** 강등한다. '적용되지 않는다'는
      판단은 추가정보가 없어도 성립할 수 있고, 무관까지 HOLD로 만들면 대시보드가
      보류로 가득 찬다.
    - `target_reason`(대상 집단 판단 불가)은 **무관도** 강등한다. 대상인지 알 수 없는데
      '무관'이라고 말하는 것은 근거 없는 확정이기 때문이다. 관련 규제를 놓치는 쪽이
      보류보다 나쁘다 (NFR-003).
    """
    reasons = [*hold_reasons]
    demotable = {Applicability.APPLICABLE}
    if target_reason:
        reasons.append(target_reason)
        demotable.add(Applicability.NOT_APPLICABLE)

    if not reasons or output.applicability not in demotable:
        return output

    hold_reasons = reasons
    merged = list(dict.fromkeys([*output.missing_context, *hold_reasons]))
    return output.model_copy(
        update={
            "applicability": Applicability.HOLD,
            "missing_context": merged,
            "reason": f"{output.reason}\n\n[보류 사유] " + " ".join(hold_reasons),
        }
    )
