"""텍스트 분할 (기획서 §7-2 Text Splitter).

한국 법령 문서 구조를 존중해 자른다. 고정 길이로 자르면 '제3조' 제목과 그 내용이
다른 청크로 갈라져, 검색된 조각만 봐서는 무슨 조문인지 알 수 없게 된다.
"""

from __future__ import annotations

import re

from app.rag.models import RagChunk, RagDocument

# 조문/항/호 또는 섹션 라벨에서 자른다.
_BOUNDARY = re.compile(
    r"(?=제\s*\d+\s*조(?:의\s*\d+)?\s*\()"      # 제3조(목적)
    r"|(?=\[(?:질의요지|회답|이유|판시사항|판결요지|참조조문)\])"
    r"|(?=\n[①-⑳])"
)
_WS = re.compile(r"[ \t]+")

DEFAULT_CHUNK_SIZE = 900
DEFAULT_OVERLAP = 120
MIN_CHUNK_SIZE = 40


def _normalize(text: str) -> str:
    return "\n".join(
        _WS.sub(" ", line).strip() for line in text.replace("\r\n", "\n").split("\n")
    ).strip()


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """구조 경계로 잘라도 여전히 긴 조각을 문장 단위로 다시 자른다."""
    if len(text) <= size:
        return [text]

    sentences = re.split(r"(?<=[.。?!])\s+", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + len(sentence) + 1 <= size:
            current = f"{current} {sentence}"
        else:
            pieces.append(current)
            # 앞 조각의 꼬리를 겹쳐 문맥이 끊기지 않게 한다.
            tail = current[-overlap:] if overlap else ""
            current = f"{tail} {sentence}".strip() if tail else sentence
        # 한 문장이 size보다 길면 강제로 자른다 (조문 하나가 통째로 긴 경우).
        while len(current) > size:
            pieces.append(current[:size])
            current = current[size - overlap :] if overlap < size else current[size:]
    if current:
        pieces.append(current)
    return pieces


def split_text(
    text: str, *, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []

    segments = [s.strip() for s in _BOUNDARY.split(normalized) if s and s.strip()]
    if not segments:
        segments = [normalized]

    chunks: list[str] = []
    buffer = ""
    for segment in segments:
        # 경계 조각이 너무 짧으면 앞 조각에 붙인다. '제1조(목적)'만 떨어지면 의미가 없다.
        if buffer and len(buffer) + len(segment) + 1 <= size:
            buffer = f"{buffer}\n{segment}"
            continue
        if buffer:
            chunks.extend(_split_long(buffer, size, overlap))
        buffer = segment
    if buffer:
        chunks.extend(_split_long(buffer, size, overlap))

    return [c.strip() for c in chunks if len(c.strip()) >= MIN_CHUNK_SIZE]


def chunk_document(
    document: RagDocument, *, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP
) -> list[RagChunk]:
    """문서를 청크로 자른다. 제목을 각 청크 앞에 붙여 맥락을 유지한다."""
    pieces = split_text(document.body, size=size, overlap=overlap)
    return [
        RagChunk.build(document, f"{document.title}\n\n{piece}" if document.title else piece, i)
        for i, piece in enumerate(pieces)
    ]
