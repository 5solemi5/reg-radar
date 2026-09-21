"""Diff Engine — 신구법 변경점 계산 (FR-005, BR-002, AP-03).

LLM은 이 모듈의 출력만 '변화'로 인정한다. 존재하지 않는 변경점을 모델이
만들어내는 경로를 원천 차단하기 위해, 변경 감지는 전부 deterministic logic이다.
"""

from __future__ import annotations

import difflib
import re

from app.diff.korean import DELEGATION_VERB
from app.domain.context import ChangeContext
from app.domain.enums import ChangeType

# ── 하위법령 위임 감지 (Q5: 누락 0건 목표) ─────────────────────────────
# 문자열 규칙 기반이므로 재현 가능하고 100% 결정적이다.
_VERB = DELEGATION_VERB

_DELEGATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("대통령령", re.compile(rf"대통령령(?:으로|이|에서)?\s*{_VERB}")),
    ("시행령", re.compile(rf"시행령(?:으로|이|에서)?\s*{_VERB}")),
    ("총리령", re.compile(rf"총리령(?:으로|이|에서)?\s*{_VERB}")),
    ("부령", re.compile(rf"[가-힣]{{0,6}}부령(?:으로|이|에서)?\s*{_VERB}")),
    ("시행규칙", re.compile(rf"시행규칙(?:으로|이|에서)?\s*{_VERB}")),
    ("고시", re.compile(rf"고시(?:로|하는|에서)\s*{_VERB}")),
    ("훈령·예규", re.compile(rf"(?:훈령|예규)(?:으로|로|이)?\s*{_VERB}")),
    ("조례", re.compile(rf"조례(?:로|으로|가)?\s*{_VERB}")),
)

# 조문 분할: 항(①②…), 호(1. 2. …), 목(가. 나. …), 문장 종결
_UNIT_SPLIT = re.compile(r"(?<=[.。])\s+|\n+|(?=[①-⑳])|(?=(?:^|\s)\d{1,2}\.\s)")
_WS = re.compile(r"[ \t]+")


def normalize(text: str) -> str:
    """비교 안정성을 위한 최소 정규화. 원문 자체는 절대 바꾸지 않는다."""
    return _WS.sub(" ", text.replace(" ", " ")).strip()


def split_units(text: str) -> list[str]:
    """조문을 항/호/문장 단위로 분할한다. diff 결과를 사람이 읽을 수 있는 단위로 만든다."""
    if not text:
        return []
    raw = _UNIT_SPLIT.split(normalize(text))
    return [u.strip() for u in raw if u and u.strip()]


def detect_delegation(text: str) -> list[str]:
    """하위법령 위임 문자열을 감지한다 (AP-03, Q5).

    반환값이 비어 있지 않으면 '조문만으로는 최종 기준을 확정할 수 없음'을 뜻하며,
    판정 단계에서 HOLD 근거로 쓰인다 (BR-003).
    """
    if not text:
        return []
    normalized = normalize(text)
    found: list[str] = []
    for label, pattern in _DELEGATION_PATTERNS:
        if pattern.search(normalized) and label not in found:
            found.append(label)
    return found


def _changed_units(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """SequenceMatcher로 추가/삭제된 단위를 뽑는다."""
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    additions: list[str] = []
    deletions: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deletions.extend(before[i1:i2])
        if tag in ("replace", "insert"):
            additions.extend(after[j1:j2])
    return additions, deletions


def compute_change(
    before_text: str | None,
    after_text: str | None,
) -> ChangeContext:
    """신구 조문 텍스트로부터 ChangeContext를 만든다.

    - before 없음 + after 있음 → NEW (신설)
    - before 있음 + after 없음 → DELETED (삭제)
    - 양쪽 동일              → UNCHANGED
    - 그 외                  → AMENDED (개정)
    """
    before_norm = normalize(before_text) if before_text else ""
    after_norm = normalize(after_text) if after_text else ""

    if not before_norm and not after_norm:
        return ChangeContext(change_type=ChangeType.UNCHANGED)

    if not before_norm:
        units = split_units(after_norm)
        return ChangeContext(
            change_type=ChangeType.NEW,
            before_text=None,
            after_text=after_text,
            additions=units,
            deletions=[],
            delegation_targets=detect_delegation(after_norm),
        )

    if not after_norm:
        units = split_units(before_norm)
        return ChangeContext(
            change_type=ChangeType.DELETED,
            before_text=before_text,
            after_text=None,
            additions=[],
            deletions=units,
            delegation_targets=detect_delegation(before_norm),
        )

    if before_norm == after_norm:
        return ChangeContext(
            change_type=ChangeType.UNCHANGED,
            before_text=before_text,
            after_text=after_text,
            delegation_targets=detect_delegation(after_norm),
        )

    additions, deletions = _changed_units(split_units(before_norm), split_units(after_norm))
    return ChangeContext(
        change_type=ChangeType.AMENDED,
        before_text=before_text,
        after_text=after_text,
        additions=additions,
        deletions=deletions,
        # 위임은 '현행(개정 후)' 기준으로 판단한다.
        delegation_targets=detect_delegation(after_norm),
    )


def inline_diff(before_text: str, after_text: str) -> str:
    """Detail 화면의 변경 전/후 표시용 unified diff 문자열 (FR-005 UI 요건)."""
    return "\n".join(
        difflib.unified_diff(
            split_units(before_text),
            split_units(after_text),
            fromfile="개정 전",
            tofile="개정 후",
            lineterm="",
        )
    )


def change_from_official_marks(
    *,
    before_text: str | None,
    after_text: str | None,
    additions: list[str],
    deletions: list[str],
) -> ChangeContext:
    """법제처가 직접 표시한 변경 구간으로 ChangeContext를 만든다 (FR-005).

    `compute_change()`는 우리가 텍스트를 비교해 변경점을 **추정**한다. 이 함수는
    법제처 신구법 비교가 `<P>`로 **명시한** 구간을 그대로 쓰므로 더 정확하다.
    신구법 응답을 받을 수 있으면 이쪽을 쓰고, 없을 때만 compute_change로 내려간다.
    """
    before_norm = normalize(before_text) if before_text else ""
    after_norm = normalize(after_text) if after_text else ""

    if not before_norm and after_norm:
        change_type = ChangeType.NEW
    elif before_norm and not after_norm:
        change_type = ChangeType.DELETED
    elif not additions and not deletions and before_norm == after_norm:
        change_type = ChangeType.UNCHANGED
    else:
        change_type = ChangeType.AMENDED

    return ChangeContext(
        change_type=change_type,
        before_text=before_text,
        after_text=after_text,
        additions=list(additions),
        deletions=list(deletions),
        delegation_targets=detect_delegation(after_norm or before_norm),
    )
