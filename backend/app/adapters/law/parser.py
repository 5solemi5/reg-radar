"""법제처 OPEN API XML 파서.

법제처 응답은 한글 태그명을 쓰며 필드 누락이 잦다. 파서는 **없는 값을 만들어내지 않고**
None으로 둔다 (BR-001). 파싱 실패는 예외로 드러내고 조용히 기본값을 채우지 않는다.
"""

from __future__ import annotations

import re
from datetime import date
from xml.etree import ElementTree as ET

from app.adapters.law.models import LawArticle, LawSnapshot, LawSummary

_DATE_8 = re.compile(r"^\d{8}$")
_WS_RUN = re.compile(r"[ \t]{2,}")


class LawParseError(ValueError):
    """법제처 응답을 해석할 수 없을 때. ER-001에 따라 임의 값으로 대체하지 않는다."""


def _text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    found = node.find(tag)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def _parse_date(value: str | None) -> date | None:
    """법제처 날짜는 'YYYYMMDD' 또는 'YYYY-MM-DD'. 그 외는 None (추측 금지)."""
    if not value:
        return None
    raw = value.strip().replace(".", "-").replace("/", "-")
    try:
        if _DATE_8.match(raw):
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        parts = raw.split("-")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None
    return None


def _clean(text: str) -> str:
    """원문 보존 원칙: 내용은 건드리지 않고 공백/개행만 정돈한다."""
    lines = [_WS_RUN.sub(" ", ln).rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def _root(xml: str | bytes) -> ET.Element:
    try:
        return ET.fromstring(xml)
    except ET.ParseError as exc:  # pragma: no cover - 방어
        raise LawParseError(f"법제처 응답 XML 파싱 실패: {exc}") from exc


# ── 목록 (lawSearch.do) ────────────────────────────────────────────────


def parse_law_list(xml: str | bytes) -> list[LawSummary]:
    root = _root(xml)
    if root.tag not in ("LawSearch", "LawService"):
        # 법제처는 인증 실패 시에도 200 + 에러 본문을 주는 경우가 있다.
        raise LawParseError(f"예상치 못한 응답 루트: <{root.tag}>. OC 값을 확인하세요.")

    results: list[LawSummary] = []
    for node in root.findall("law"):
        law_name = _text(node, "법령명한글")
        law_id = _text(node, "법령ID")
        if not law_name or not law_id:
            continue  # 식별 불가 항목은 버린다. 임의 채움 금지.
        results.append(
            LawSummary(
                law_id=law_id,
                mst=_text(node, "법령일련번호"),
                law_name=law_name,
                law_type=_text(node, "법령구분명"),
                ministry=_text(node, "소관부처명"),
                promulgation_date=_parse_date(_text(node, "공포일자")),
                promulgation_no=_text(node, "공포번호"),
                effective_date=_parse_date(_text(node, "시행일자")),
                revision_type=_text(node, "제개정구분명"),
                detail_link=_text(node, "법령상세링크"),
            )
        )
    return results


def parse_total_count(xml: str | bytes) -> int:
    value = _text(_root(xml), "totalCnt")
    return int(value) if value and value.isdigit() else 0


# ── 본문 (lawService.do) ───────────────────────────────────────────────


def _article_no(node: ET.Element) -> str | None:
    """'15' + 가지번호 '2' → '제15조의2'."""
    no = _text(node, "조문번호")
    if not no:
        return None
    branch = _text(node, "조문가지번호")
    return f"제{no}조의{branch}" if branch and branch != "0" else f"제{no}조"


def _article_text(node: ET.Element) -> str:
    """조문내용 + 항/호/목 내용을 원문 순서대로 이어붙인다."""
    parts: list[str] = []
    head = _text(node, "조문내용")
    if head:
        parts.append(head)
    for hang in node.findall("항"):
        hang_text = _text(hang, "항내용")
        if hang_text:
            parts.append(hang_text)
        for ho in hang.findall("호"):
            ho_text = _text(ho, "호내용")
            if ho_text:
                parts.append(ho_text)
            for mok in ho.findall("목"):
                mok_text = _text(mok, "목내용")
                if mok_text:
                    parts.append(mok_text)
    return _clean("\n".join(parts))


def _parse_articles(container: ET.Element | None) -> list[LawArticle]:
    """본문 조문을 파싱한다.

    법제처는 편/장/절 제목도 <조문단위>로 내려보내며(<조문여부>전문</조문여부>),
    이들은 바로 뒤 조문과 **같은 조문번호를 공유한다**. 그대로 두면 '제1조'가
    "제1장 총칙"으로 잡혀 인용 검증(FR-021)과 LLM 컨텍스트가 오염되므로
    조문 목록에서 제외하고, 대신 소속 장 제목으로만 보존한다.
    """
    if container is None:
        return []

    articles: list[LawArticle] = []
    current_chapter: str | None = None

    for node in container.iter("조문단위"):
        if (_text(node, "조문여부") or "조문") != "조문":
            heading = _clean(_text(node, "조문내용") or "")
            if heading:
                current_chapter = heading
            continue

        text = _article_text(node)
        no = _article_no(node)
        if not text or not no:
            continue

        articles.append(
            LawArticle(
                article_no=no,
                article_key=_text(node, "조문키"),
                article_title=_text(node, "조문제목"),
                chapter=current_chapter,
                effective_date=_parse_date(_text(node, "조문시행일자")),
                original_text=text,
                is_supplementary=False,
            )
        )
    return articles


def _parse_supplementary(container: ET.Element | None) -> list[LawArticle]:
    """부칙을 파싱한다. 공포번호로 식별해 개정 회차별로 구분한다."""
    if container is None:
        return []

    articles: list[LawArticle] = []
    for node in container.iter("부칙단위"):
        text = _clean("\n".join(t.text.strip() for t in node.iter("부칙내용") if t.text))
        if not text:
            continue
        no_raw = _text(node, "부칙공포번호")
        promulgated = _parse_date(_text(node, "부칙공포일자"))
        label = "부칙"
        if no_raw:
            label += f" 제{no_raw.lstrip('0') or no_raw}호"
        if promulgated:
            label += f"({promulgated.isoformat()})"
        articles.append(
            LawArticle(
                article_no=label,
                effective_date=promulgated,
                original_text=text,
                is_supplementary=True,
            )
        )
    return articles


def parse_law_detail(xml: str | bytes, *, source_url: str | None = None) -> LawSnapshot:
    root = _root(xml)
    basic = root.find("기본정보")
    if basic is None:
        raise LawParseError("법령 본문 응답에 <기본정보>가 없습니다. OC/MST 값을 확인하세요.")

    law_name = _text(basic, "법령명_한글") or _text(basic, "법령명한글")
    law_id = _text(basic, "법령ID")
    if not law_name or not law_id:
        raise LawParseError("법령 본문 응답에서 법령ID/법령명을 찾지 못했습니다.")

    articles: list[LawArticle] = []
    articles.extend(_parse_articles(root.find("조문")))
    articles.extend(_parse_supplementary(root.find("부칙")))

    return LawSnapshot(
        law_id=law_id,
        mst=_text(basic, "법령일련번호"),
        law_name=law_name,
        law_type=_text(basic, "법종구분"),
        ministry=_text(basic, "소관부처"),
        promulgation_date=_parse_date(_text(basic, "공포일자")),
        effective_date=_parse_date(_text(basic, "시행일자")),
        revision_type=_text(basic, "제개정구분"),
        source_url=source_url,
        articles=articles,
    )
