"""규모(상시근로자 수) 기준 판정 — 코드로 계산한다 (AP-03).

조문의 "상시 10명 이상" 같은 수치 기준과 사용자의 상시근로자 수를 비교하는 일은
산술이지 의미 해석이 아니다. LLM에 맡기면 '용어 정의가 불명확하다'는 이유로
판정을 회피해 과도한 보류를 만든다 — 실제로 첫 E2E에서 그 현상이 관측됐다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.diff.korean import HADA, NOT_DO_VERB

# "상시 10명 이상", "상시근로자 수가 300명 미만", "근로자 5명 이상",
# "상시 근로자가 5명 미만인"
#
# 조사(가/이/는/은)를 빼먹으면 중대재해처벌법 제3조의 "상시 근로자가 5명 미만인
# 사업"을 통째로 놓친다. 규모 기준을 못 보면 코드가 계산을 포기하고 LLM이 혼자
# 판단하게 되는데, 그러라고 만든 모듈이 아니다 (AP-03).
_SUBJECT = r"근로자\s*(?:수\s*)?(?:가|이|는|은)?\s*"
_HEADCOUNT = re.compile(
    rf"(?:상시\s*(?:{_SUBJECT})?|{_SUBJECT})"
    r"(\d[\d,]*)\s*명\s*(이상|이하|미만|초과)"
)

# 이 기준이 '적용을 배제하는 단서'에 들어 있는지 가르는 표현.
# 같은 '상시 30명'이라도 적용 조건이냐 배제 조건이냐에 따라 결론이 정반대다.
_EXCLUSION = re.compile(
    rf"(?:그러하지|적용하지|적용되지|해당하지)\s*{NOT_DO_VERB}"
    rf"|적용을\s*제외|제외{HADA}"
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
    in_exclusion_clause: bool = False
    """이 기준이 적용을 배제하는 단서에 들어 있는가.

    근로자참여법 제4조는 "상시 30명 미만은 그러하지 아니하다"로 설치 의무를
    **배제**한다. 이걸 구분하지 않고 '충족/미충족'으로만 알려주면, 80명 회사가
    "상시 30명 미만 → 미충족"을 보고 적용 안 된다고 읽는다. 정확히 거꾸로다.
    """

    def satisfied_by(self, count: int) -> bool:
        """숫자가 이 기준 표현에 해당하는가. 적용 여부가 아니라 산술이다."""
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
            found = ", ".join(f"{t.raw}{self._tag(t)}" for t in self.thresholds)
            return (
                f"조문의 규모 기준: {found}\n"
                "사용자 상시근로자 수: 미상 → 해당 여부를 계산할 수 없습니다."
            )

        lines = [f"사용자 상시근로자 수: {self.employee_count}명 (프로필 입력값)"]
        for t in self.thresholds:
            hit = "해당함" if t.satisfied_by(self.employee_count) else "해당하지 않음"
            lines.append(
                f"  · 기준 '{t.raw}'{self._tag(t)} → {self.employee_count}명은 {hit}"
            )
        lines.append(
            "위 '해당/해당하지 않음'은 코드가 계산한 산술입니다. 숫자를 다시 의심하거나 "
            "'정의가 불명확하다'는 이유로 판정을 회피하지 마십시오."
        )
        if any(t.in_exclusion_clause for t in self.thresholds):
            # 산술 결과와 적용 여부가 반대로 움직이는 경우다. 명시하지 않으면
            # '해당하지 않음'을 '적용되지 않음'으로 읽는다.
            lines.append(
                "[적용 배제] 표시된 기준은 적용을 **배제**하는 단서입니다. "
                "여기에 해당하면 조문이 적용되지 않고, 해당하지 않으면 배제되지 않습니다."
            )
        return "\n".join(lines)

    @staticmethod
    def _tag(threshold: Threshold) -> str:
        return " [적용 배제]" if threshold.in_exclusion_clause else ""


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
        results.append(
            Threshold(
                value=value,
                operator=operator,
                raw=m.group(0).strip(),
                in_exclusion_clause=_is_exclusion(text, m.end()),
            )
        )
    return results


def _is_exclusion(text: str, pos: int) -> bool:
    """이 위치의 기준이 적용 배제 단서 안에 있는가.

    기준 뒤 같은 문장에서 배제 표현을 찾는다. "상시 30명 미만의 근로자를 사용하는
    사업장은 그러하지 아니하다"처럼 배제 표현은 항상 기준보다 뒤에 온다.
    """
    tail = text[pos:]
    end = min(
        (i for i in (tail.find("\n"), tail.find("다. ")) if i != -1),
        default=len(tail),
    )
    return bool(_EXCLUSION.search(tail[: end + 2]))


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
