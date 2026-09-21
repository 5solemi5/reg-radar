"""RAG 문서 수집 (FR-013, 기획서 §7-1).

법제처 OPEN API가 법령 원문 말고도 실무 맥락 자료를 제공한다. 정부 사이트를
스크래핑하는 대신 이쪽을 쓰는 이유는 출처·기관·일자 metadata가 이미 구조화되어
있고, 원문 링크가 있어 사용자가 직접 확인할 수 있기 때문이다 (FR-013).

| 기획서의 문서 유형 | 법제처 target | 설명 |
|---|---|---|
| FAQ·행정해석 | expc | 법령해석례. 질의요지/회답/이유 구조 |
| 정부기관 가이드 | admrul | 행정규칙(훈령·예규·고시) |
| 검증된 사례/결정례 | prec | 판례 |
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree as ET

from app.adapters.law.client import LawApiClient, LawApiError
from app.adapters.law.parser import _clean, _parse_date, _text
from app.domain.enums import DocType
from app.rag.models import RagDocument

logger = logging.getLogger(__name__)

# 본문에 인용된 법령명. metadata filter에 쓴다.
# 예: 「개인정보 보호법」 제35조의2 → '개인정보 보호법'
_QUOTED_LAW = re.compile(r"[「『]([^」』]{2,40}?(?:법|법률|령|규칙|고시))[」』]")


def extract_law_names(*texts: str) -> list[str]:
    """문서가 다루는 법령명을 뽑는다.

    한국 법령 문서는 다른 법령을 「」로 인용하는 관행이 확고해서, 이 규칙만으로도
    "이 문서가 어떤 법에 관한 것인가"를 꽤 정확히 알 수 있다. LLM을 쓰지 않는다.
    """
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _QUOTED_LAW.finditer(text):
            name = match.group(1).strip()
            if name and name not in found:
                found.append(name)
    return found


def _public_url(target: str, doc_id: str) -> str:
    return f"https://www.law.go.kr/DRF/lawService.do?target={target}&ID={doc_id}&type=HTML"


class LawPortalLoader:
    """법제처에서 참고자료를 수집한다."""

    def __init__(self, client: LawApiClient):
        self._client = client

    async def _search(self, target: str, query: str, display: int) -> list[ET.Element]:
        xml = await self._client._get(
            "/lawSearch.do", self._client._params(target=target, query=query, display=display)
        )
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            logger.info("검색 응답이 XML이 아님: target=%s query=%s", target, query)
            return []
        return root.findall(target)

    async def _detail(self, target: str, doc_id: str) -> ET.Element | None:
        xml = await self._client._get(
            "/lawService.do", self._client._params(target=target, ID=doc_id)
        )
        try:
            return ET.fromstring(xml)
        except ET.ParseError:
            logger.info("상세 응답이 XML이 아님: target=%s id=%s", target, doc_id)
            return None

    # ── 법령해석례 (행정해석) ──────────────────────────────────────────

    async def load_interpretations(self, query: str, *, limit: int = 5) -> list[RagDocument]:
        documents: list[RagDocument] = []
        for item in await self._search("expc", query, limit):
            doc_id = _text(item, "법령해석례일련번호")
            if not doc_id:
                continue
            try:
                detail = await self._detail("expc", doc_id)
            except LawApiError as exc:
                logger.info("법령해석례 상세 실패 id=%s: %s", doc_id, exc)
                continue
            if detail is None:
                continue

            title = _text(detail, "안건명") or _text(item, "안건명") or ""
            question = _text(detail, "질의요지") or ""
            answer = _text(detail, "회답") or ""
            reason = _text(detail, "이유") or ""
            if not (answer or reason):
                continue

            # 질의-회답 구조를 유지한다. 회답만 떼면 무슨 질문에 대한 답인지 사라진다.
            body = _clean(
                "\n\n".join(
                    part for part in (
                        f"[질의요지] {question}" if question else "",
                        f"[회답] {answer}" if answer else "",
                        f"[이유] {reason}" if reason else "",
                    ) if part
                )
            )

            documents.append(
                RagDocument(
                    doc_id=f"expc-{doc_id}",
                    title=title,
                    body=body,
                    doc_type=DocType.INTERPRETATION,
                    source=_public_url("expc", doc_id),
                    agency=_text(detail, "해석기관명") or _text(item, "회신기관명"),
                    published_at=_parse_date(
                        _text(detail, "해석일자") or _text(item, "회신일자")
                    ),
                    related_law_names=extract_law_names(title, question, answer),
                    extra={"안건번호": _text(detail, "안건번호") or ""},
                )
            )
        return documents

    # ── 행정규칙 (정부기관 가이드) ────────────────────────────────────

    async def load_admin_rules(self, query: str, *, limit: int = 5) -> list[RagDocument]:
        documents: list[RagDocument] = []
        for item in await self._search("admrul", query, limit):
            doc_id = _text(item, "행정규칙일련번호")
            if not doc_id:
                continue
            try:
                detail = await self._detail("admrul", doc_id)
            except LawApiError as exc:
                logger.info("행정규칙 상세 실패 id=%s: %s", doc_id, exc)
                continue
            if detail is None:
                continue

            title = _text(item, "행정규칙명") or ""
            paragraphs = [
                _clean(node.text) for node in detail.iter("조문내용")
                if node.text and node.text.strip()
            ]
            body = _clean("\n".join(paragraphs))
            if not body:
                continue

            documents.append(
                RagDocument(
                    doc_id=f"admrul-{doc_id}",
                    title=title,
                    body=body,
                    doc_type=DocType.GUIDE,
                    source=_public_url("admrul", doc_id),
                    agency=_text(item, "소관부처명"),
                    published_at=_parse_date(
                        _text(item, "시행일자") or _text(item, "발령일자")
                    ),
                    related_law_names=extract_law_names(title, body),
                    extra={"종류": _text(item, "행정규칙종류") or ""},
                )
            )
        return documents

    # ── 판례 (검증된 사례) ────────────────────────────────────────────

    async def load_precedents(self, query: str, *, limit: int = 3) -> list[RagDocument]:
        documents: list[RagDocument] = []
        for item in await self._search("prec", query, limit):
            doc_id = _text(item, "판례일련번호")
            if not doc_id:
                continue
            try:
                detail = await self._detail("prec", doc_id)
            except LawApiError as exc:
                logger.info("판례 상세 실패 id=%s: %s", doc_id, exc)
                continue
            if detail is None:
                continue

            title = _text(item, "사건명") or ""
            parts = [
                _clean(_text(detail, tag) or "")
                for tag in ("판시사항", "판결요지", "참조조문")
            ]
            body = _clean("\n\n".join(p for p in parts if p))
            if not body:
                continue

            documents.append(
                RagDocument(
                    doc_id=f"prec-{doc_id}",
                    title=title,
                    body=body,
                    doc_type=DocType.CASE,
                    source=_public_url("prec", doc_id),
                    agency=_text(item, "법원명"),
                    published_at=_parse_date(_text(item, "선고일자")),
                    related_law_names=extract_law_names(title, body),
                    extra={"사건번호": _text(item, "사건번호") or ""},
                )
            )
        return documents

    async def load_all(
        self, query: str, *, interpretations: int = 5, rules: int = 5, precedents: int = 3
    ) -> list[RagDocument]:
        """한 검색어에 대해 세 종류를 모두 수집한다.

        일부가 실패해도 나머지는 살린다. 참고자료는 없어도 되는 것이므로
        (BR-005) 수집 실패가 분석을 막아서는 안 된다.
        """
        documents: list[RagDocument] = []
        for label, coroutine in (
            ("법령해석례", self.load_interpretations(query, limit=interpretations)),
            ("행정규칙", self.load_admin_rules(query, limit=rules)),
            ("판례", self.load_precedents(query, limit=precedents)),
        ):
            try:
                documents.extend(await coroutine)
            except LawApiError as exc:
                logger.info("%s 수집 실패 query=%s: %s", label, query, exc)

        # 수집 검색어를 관련 법령에 넣는다. 판례 제목은 「」로 법령을 인용하지
        # 않아(예: '개인정보보호법위반[...]') 본문 추출만으로는 태그가 비어 있고,
        # 그러면 법령명 필터에서 전부 탈락한다.
        tagged: list[RagDocument] = []
        for document in documents:
            if not document.is_usable:
                continue
            names = document.related_law_names
            if query not in names:
                names = [*names, query]
            tagged.append(document.model_copy(update={"related_law_names": names}))
        return tagged
