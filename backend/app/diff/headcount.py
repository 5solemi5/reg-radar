"""규모(상시근로자 수) 기준 판정 — 코드로 계산한다 (AP-03).

조문의 "상시 10명 이상" 같은 수치 기준과 사용자의 상시근로자 수를 비교하는 일은
산술이지 의미 해석이 아니다. LLM에 맡기면 '용어 정의가 불명확하다'는 이유로
판정을 회피해 과도한 보류를 만든다 — 실제로 첫 E2E에서 그 현상이 관측됐다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# "상시 10명 이상", "상시근로자 수가 300명 미만", "근로자 5명 이상"
_HEADCOUNT = re.compile(
    r"(?:상시\s*(?:근로자\s*(?:수가?)?\s*)?|근로자\s*)"
    r"(\d[\d,]*)\s*명\s*(이상|이하|미만|초과)"
)

_OPERATORS = {
    "이상": lambda n, t: n >= t,
    "초과": lambda n, t: n > t,
    "이하": lambda n, t: n <= t,
    "미만": lambda n, t: n < t,
}


class SizeVerdict(StrEnum):
    NO_CONDITION = "NO_CONDITION"   # 조문에 규모 기준이 없음
    UNKNOWN = "UNKNOWN"             # 기준은 있는데 사용자 인원 미상 → HOLD 근거
    MEETS = "MEETS"                 # 모든 기준을 충족
    BELOW = "BELOW"                 # 어떤 기준도 충족하지 못함
    PARTIAL = "PARTIAL"             # 기준이 여럿이고 일부만 충족 (단서 조항 등)


@dataclass(frozen=True)
class Threshold:
    value: int
    operator: str
    raw: str

    def satisfied_by(self, count: int) -> bool:
        return _OPERATORS[self.operator](count, self.value)


@dataclass(frozen=True)
class SizeEvaluation:
    verdict: SizeVerdict
    thresholds: list[Threshold]
    employee_count: int | None
    satisfied: list[Threshold]
    unsatisfied: list[Threshold]

    @property
    def has_condition(self) -> bool:
        return bool(self.thresholds)

    def to_prompt_block(self) -> str:
        """C4에 주입할 '코드가 계산한 사실' 블록."""
        if not self.thresholds:
            return "(조문에 상시근로자 수 기준이 없습니다.)"
        if self.employee_count is None:
            found = ", ".join(t.raw for t in self.thresholds)
            return (
                f"조문의 규모 기준: {found}\n"
                "사용자 상시근로자 수: 미상 → 충족 여부를 계산할 수 없습니다."
            )
        lines = [f"사용자 상시근로자 수: {self.employee_count}명 (프로필 입력값)"]
        for t in self.thresholds:
            mark = "충족" if t.satisfied_by(self.employee_count) else "미충족"
            lines.append(f"  · 기준 '{t.raw}' → {mark}")
        lines.append(
            "위 충족/미충족은 코드가 계산한 값입니다. 이 값을 다시 의심하거나 "
            "'정의가 불명확하다'는 이유로 판정을 회피하지 마십시오."
        )
        return "\n".join(lines)


def extract_thresholds(text: str) -> list[Threshold]:
    """조문에서 상시근로자 수 기준을 추출한다."""
    seen: set[tuple[int, str]] = set()
    results: list[Threshold] = []
    for m in _HEADCOUNT.finditer(text):
        value = int(m.group(1).replace(",", ""))
        operator = m.group(2)
        if (value, operator) in seen:
            continue
        seen.add((value, operator))
        results.append(Threshold(value=value, operator=operator, raw=m.group(0).strip()))
    return results


def evaluate(text: str, employee_count: int | None) -> SizeEvaluation:
    thresholds = extract_thresholds(text)

    if not thresholds:
        return SizeEvaluation(SizeVerdict.NO_CONDITION, [], employee_count, [], [])

    if employee_count is None:
        return SizeEvaluation(SizeVerdict.UNKNOWN, thresholds, None, [], thresholds)

    satisfied = [t for t in thresholds if t.satisfied_by(employee_count)]
    unsatisfied = [t for t in thresholds if not t.satisfied_by(employee_count)]

    if not unsatisfied:
        verdict = SizeVerdict.MEETS
    elif not satisfied:
        verdict = SizeVerdict.BELOW
    else:
        verdict = SizeVerdict.PARTIAL

    return SizeEvaluation(verdict, thresholds, employee_count, satisfied, unsatisfied)
