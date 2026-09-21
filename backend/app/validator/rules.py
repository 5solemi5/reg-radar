"""개별 검증 규칙 (FR-020, FR-021, BR-001).

각 규칙은 순수 함수다. 판정 로직과 분리해 단위 테스트로 고정한다.
"""

from __future__ import annotations

import re

from app.domain.context import ContextPacket

_WS = re.compile(r"\s+")

# AI 자유 서술에 등장하는 조문 참조. 예: 제15조, 제15조의2, 제 15 조
_ARTICLE_REF = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")

# AI 자유 서술에 등장하는 날짜. 예: 2026년 9월 1일 / 2026-09-01 / 2026.9.1
_DATE_REF = re.compile(
    r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?"
)

# RAG 인용 마커. 예: [R1]
_RAG_MARKER = re.compile(r"\[R\s*(\d+)\]")


def normalize_for_match(text: str) -> str:
    """인용 대조용 정규화.

    공백·개행 차이만 흡수한다. 글자를 바꾸거나 지우지 않으므로,
    내용이 다른 문장이 통과할 여지는 없다.
    """
    return _WS.sub(" ", text).strip()


def verify_citations(spans: list[str], original_text: str) -> tuple[list[str], list[str]]:
    """FR-021. 인용이 원문에 실제로 존재하는지 substring 검증.

    반환: (검증 통과 인용, 탈락 인용)
    """
    haystack = normalize_for_match(original_text)
    verified: list[str] = []
    dropped: list[str] = []
    for span in spans:
        candidate = normalize_for_match(span)
        if candidate and candidate in haystack:
            verified.append(span)
        else:
            dropped.append(span)
    return verified, dropped


def _normalize_article_ref(match: re.Match[str]) -> str:
    main, branch = match.group(1), match.group(2)
    return f"제{int(main)}조의{int(branch)}" if branch else f"제{int(main)}조"


def find_fabricated_article_refs(ai_text: str, packet: ContextPacket) -> list[str]:
    """BR-001. AI 서술에 등장한 조문번호가 근거 범위 밖이면 위조로 본다.

    허용되는 참조:
      - 분석 대상 조문 자신 (예: 제26조)
      - 조문 원문 안에서 실제로 인용된 다른 조문 (예: "제10조에 따른")
    """
    allowed = {normalize_for_match(packet.law.article_no)}
    for m in _ARTICLE_REF.finditer(packet.law.original_text):
        allowed.add(_normalize_article_ref(m))

    fabricated: list[str] = []
    for m in _ARTICLE_REF.finditer(ai_text):
        ref = _normalize_article_ref(m)
        if ref not in allowed and ref not in fabricated:
            fabricated.append(ref)
    return fabricated


def find_fabricated_dates(ai_text: str, packet: ContextPacket) -> list[str]:
    """BR-001. AI 서술에 등장한 날짜가 공식 날짜도, 원문에 있는 날짜도 아니면 위조."""
    allowed: set[tuple[int, int, int]] = set()
    for d in (packet.law.effective_date, packet.law.promulgation_date):
        if d:
            allowed.add((d.year, d.month, d.day))
    for m in _DATE_REF.finditer(packet.law.original_text):
        allowed.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))

    fabricated: list[str] = []
    for m in _DATE_REF.finditer(ai_text):
        key = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if key not in allowed:
            label = f"{key[0]}-{key[1]:02d}-{key[2]:02d}"
            if label not in fabricated:
                fabricated.append(label)
    return fabricated


def find_phantom_rag_refs(ai_text: str, packet: ContextPacket) -> list[str]:
    """BR-005. 참고자료가 없거나 범위 밖인데 [Rn]을 인용하면 출처 생성이다."""
    available = len(packet.rag)
    phantom: list[str] = []
    for m in _RAG_MARKER.finditer(ai_text):
        idx = int(m.group(1))
        if idx < 1 or idx > available:
            marker = f"[R{idx}]"
            if marker not in phantom:
                phantom.append(marker)
    return phantom
